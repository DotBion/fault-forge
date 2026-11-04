"""Matched-random baselines: answer "is Muse just picking the right fault family?".

Two open-loop arms (no feedback, no LLM), sampled from Muse's EMPIRICAL proposal distribution measured over all
784 Muse proposals of data/cmp/muse_seed{0,1,2}.jsonl (random fallbacks excluded):

  matchfam   fault FAMILY matched: the fault-kind combination (count of RW faults, their types, heater y/n,
             leak y/n; e.g. "heater+leak+rw_torque_derate+rw_torque_derate") is drawn from Muse's empirical joint
             combo distribution (77% two-wheel vs 15% for plain random). Wheel indices distinct uniform.
             All continuous params (beta, f0, onsets, severity, heater W, leak Nm/axis) uniform exactly like
             the plain random arm.
  matchall   family AND marginals matched: as matchfam, but every continuous param is drawn independently from
             Muse's pooled empirical marginal for that param (bootstrap of observed values: beta, f0, each fault's
             onset fraction, severity per RW fault type, heater W, leak Nm, leak axis vector). Joint structure /
             per-scenario conditioning / round-to-round adaptation is destroyed. NB: these marginals are what Muse
             converged to WITH feedback, so this arm is an optimistic "informed random" baseline.

  python3 src/matched_search.py --arm matchfam --seed 0 --n 232 --workers 3
  -> data/matched/matchfam_seed0.jsonl  (resumable: ids already present are skipped)

Requires the corrected (consecutive) wheel_saturation rule in ff_sim.py; refuses to run otherwise.
"""
import argparse
import glob
import inspect
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
from search import T_end, _run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "matched")


def satfix_landed():
    """True if ff_sim uses the corrected consecutive wheel_saturation rule (CFG sat_rule, no legacy env override)."""
    src = inspect.getsource(ff_sim.run_scenario)
    rule = os.environ.get("FF_SAT_RULE") or ff_sim.CFG.get("sat_rule")
    return rule == "consecutive" and "sat_s[i] = 0.0" in src


def muse_bank():
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "cmp", "muse_seed[0-9].jsonl"))):
        for l in open(p):
            r = json.loads(l)
            if r.get("source", "muse") == "muse":
                rows.append(r["params"])
    Te = T_end()
    combos = {}
    for p in rows:
        k = (tuple(sorted(f["type"] for f in p["rw_faults"])), p["heater"] is not None, p["torque_leak"] is not None)
        combos[k] = combos.get(k, 0) + 1
    keys = sorted(combos)
    w = np.array([combos[k] for k in keys], float)
    emp = {
        "beta": [p["orbit"]["beta_deg"] for p in rows],
        "f0": [p["orbit"]["f0_deg"] for p in rows],
        "rw_onset": [f["onset_s"] / Te for p in rows for f in p["rw_faults"]],
        "sev_torque_derate": [f["severity"] for p in rows for f in p["rw_faults"] if f["type"] == "torque_derate"],
        "sev_friction": [f["severity"] for p in rows for f in p["rw_faults"] if f["type"] == "friction"],
        "heater_onset": [p["heater"]["onset_s"] / Te for p in rows if p["heater"]],
        "heater_W": [p["heater"]["power_W"] for p in rows if p["heater"]],
        "leak_onset": [p["torque_leak"]["onset_s"] / Te for p in rows if p["torque_leak"]],
        "leak_Nm": [p["torque_leak"]["mag_Nm"] for p in rows if p["torque_leak"]],
        "leak_axis": [p["torque_leak"]["axis"] for p in rows if p["torque_leak"]],
    }
    return keys, w / w.sum(), emp, len(rows)


def sample(rng, arm, keys, probs, emp):
    R, Te = ff_sim.RANGES, T_end()
    k = keys[rng.choice(len(keys), p=probs)]
    rwtypes, has_h, has_l = k
    pick = lambda name: emp[name][int(rng.integers(len(emp[name])))]
    if arm == "matchall":
        beta, f0 = float(pick("beta")), float(pick("f0"))
        on = lambda name: round(float(pick(name)) * Te, 1)
    else:
        beta, f0 = float(rng.uniform(*R["beta_deg"])), float(rng.uniform(*R["f0_deg"]))
        on = lambda name: round(float(rng.uniform(*R["onset_frac"]) * Te), 1)
    p = {"orbit": {"beta_deg": round(beta, 2), "f0_deg": round(f0, 2)}, "rw_faults": [], "heater": None,
         "torque_leak": None}
    wheels = rng.choice(4, size=len(rwtypes), replace=False)
    types = list(rwtypes); rng.shuffle(types)
    for wh, t in zip(wheels, types):
        sev = float(pick(f"sev_{t}")) if arm == "matchall" else float(rng.uniform(*R["rw_severity"]))
        p["rw_faults"].append({"wheel": int(wh), "onset_s": on("rw_onset"), "type": t, "severity": round(sev, 3)})
    if has_h:
        pw = float(pick("heater_W")) if arm == "matchall" else float(rng.uniform(*R["heater_W"]))
        p["heater"] = {"onset_s": on("heater_onset"), "power_W": round(pw, 2)}
    if has_l:
        if arm == "matchall":
            mag, ax = float(pick("leak_Nm")), np.array(pick("leak_axis"), float)
        else:
            mag = float(rng.uniform(*R["leak_Nm"])); ax = rng.normal(size=3)
        ax /= np.linalg.norm(ax)
        p["torque_leak"] = {"onset_s": on("leak_onset"), "mag_Nm": float(f"{mag:.3e}"),
                            "axis": [round(float(a), 4) for a in ax]}
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["matchfam", "matchall"], required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dry", action="store_true", help="only write the sampled params")
    a = ap.parse_args()
    if not a.dry and not satfix_landed():
        sys.exit("ff_sim.py still has the cumulative wheel_saturation rule; refusing to run (wait for the fix)")
    os.makedirs(OUT, exist_ok=True)
    keys, probs, emp, nb = muse_bank()
    salt = {"matchfam": 11, "matchall": 22}[a.arm]
    jobs = []
    for i in range(a.n):
        rng = np.random.default_rng([salt, a.seed, i])   # per-run seed: every run regenerates independently
        jobs.append((i, a.seed, sample(rng, a.arm, keys, probs, emp)))
    out = os.path.join(OUT, f"{a.arm}_seed{a.seed}.jsonl")
    if a.dry:
        json.dump([j[2] for j in jobs], open(out.replace(".jsonl", "_params.json"), "w"))
        print("wrote params", len(jobs)); return
    done = set()
    if os.path.exists(out):
        for l in open(out):
            try:
                done.add(json.loads(l)["id"])
            except Exception:  # noqa: BLE001  (torn last line after an interruption)
                pass
        # rewrite without a torn line
        good = [l for l in open(out) if l.strip().endswith("}")]
        open(out, "w").writelines(good)
    todo = [j for j in jobs if j[0] not in done]
    print(f"{a.arm} seed {a.seed}: {len(done)} done, {len(todo)} to run (bank {nb} Muse proposals)", flush=True)
    t0 = time.perf_counter()
    with open(out, "a") as f, Pool(a.workers) as pool:
        for k, res in enumerate(pool.imap(_run, todo)):
            res["source"] = a.arm
            f.write(json.dumps(res) + "\n"); f.flush()
            if (k + 1) % 25 == 0:
                print(f"  {k+1}/{len(todo)} {time.perf_counter()-t0:.0f}s", flush=True)
    print("done", out, flush=True)


if __name__ == "__main__":
    main()
