"""Middle arm "oneshot": ONE Muse call per seed returns a bank of candidate scenarios (same system prompt as the
Muse-guided arm, but no simulation results, ever); the rest of the sim budget is spent on plain random mutations of
bank members (parent chosen uniformly, no selection on outcomes, no feedback).

  python3 src/oneshot_search.py bank --seed 0 --bank 40      -> data/matched/oneshot_seed0_bank.json (+ provenance)
  python3 src/oneshot_search.py run  --seed 0 --n 232        -> data/matched/oneshot_seed0.jsonl (resumable)

Model muse-spark-1.3 at https://api.meta.ai/v1/chat/completions via src/muse_client.py (model, response id and
request id are logged; MUSE_API_KEY is never stored).
"""
import argparse
import copy
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
from llm_search import PREFACE, system_text, validate  # noqa: E402
from matched_search import satfix_landed  # noqa: E402
from muse_client import chat_logged  # noqa: E402
from search import T_end, _run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "matched")


def make_bank(seed, n):
    sysmsg = system_text().replace("exactly N scenario objects", f"exactly {n} scenario objects")
    user = (PREFACE + "No simulations have been run yet and you will receive NO results back: this is your only "
            f"chance. Propose exactly {n} diverse test scenarios that together cover as many physically distinct "
            "failure mechanisms of the recovery policy as possible.")
    rng = np.random.default_rng(50_000 + seed)
    content, prov = chat_logged([{"role": "system", "content": sysmsg}, {"role": "user", "content": user}],
                                seed=seed * 1000 + 777, max_tokens=24000)
    d = json.loads(content)
    bank, repairs = [], 0
    for s in (d.get("scenarios") or [])[:n]:
        try:
            p, fx = validate(s, rng); repairs += fx
            bank.append({"params": p, "hypothesis": str(s.get("hypothesis", ""))[:200]})
        except Exception:  # noqa: BLE001
            repairs += 1
    out = {"seed": seed, "requested": n, "returned": len(d.get("scenarios") or []), "valid": len(bank),
           "repairs": repairs, "analysis": d.get("analysis", ""), "provenance": prov, "bank": bank,
           "prompt": {"system": sysmsg, "user": user}}
    json.dump(out, open(os.path.join(OUT, f"oneshot_seed{seed}_bank.json"), "w"), indent=1)
    print(f"seed {seed}: bank {len(bank)}/{n} valid, model={prov.get('model')} response_id={prov.get('response_id')} "
          f"request_id={prov.get('request_id')} latency={prov.get('latency_s')}s")


def mutate(p, rng):
    """Plain random mutation within the search space (no outcome information)."""
    R, Te = ff_sim.RANGES, T_end()
    on_hi = R["onset_frac"][1] * Te
    q = copy.deepcopy(p)
    g = lambda x, lo, hi, frac=0.1: float(np.clip(x + rng.normal() * frac * (hi - lo), lo, hi))
    if rng.random() < 0.5: q["orbit"]["beta_deg"] = round(g(q["orbit"]["beta_deg"], *R["beta_deg"]), 2)
    if rng.random() < 0.5: q["orbit"]["f0_deg"] = round((q["orbit"]["f0_deg"] + rng.normal() * 36.0) % 360.0, 2)
    for f in q["rw_faults"]:
        if rng.random() < 0.5: f["onset_s"] = round(g(f["onset_s"], 0, on_hi), 1)
        if rng.random() < 0.5: f["severity"] = round(g(f["severity"], *R["rw_severity"]), 3)
        if rng.random() < 0.1: f["type"] = "friction" if f["type"] == "torque_derate" else "torque_derate"
    if q["rw_faults"] and rng.random() < 0.15:      # move one fault to another free wheel
        used = {f["wheel"] for f in q["rw_faults"]}
        free = [w for w in range(4) if w not in used]
        q["rw_faults"][int(rng.integers(len(q["rw_faults"])))]["wheel"] = int(rng.choice(free))
    if q["heater"] is not None:
        if rng.random() < 0.5: q["heater"]["onset_s"] = round(g(q["heater"]["onset_s"], 0, on_hi), 1)
        if rng.random() < 0.5: q["heater"]["power_W"] = round(g(q["heater"]["power_W"], *R["heater_W"]), 2)
    if q["torque_leak"] is not None:
        L = q["torque_leak"]
        if rng.random() < 0.5: L["onset_s"] = round(g(L["onset_s"], 0, on_hi), 1)
        if rng.random() < 0.5: L["mag_Nm"] = float(f"{g(L['mag_Nm'], *R['leak_Nm']):.3e}")
        if rng.random() < 0.3:
            ax = np.array(L["axis"], float) + rng.normal(size=3) * 0.3; ax /= np.linalg.norm(ax)
            L["axis"] = [round(float(a), 4) for a in ax]
    r = rng.random()                                 # structural: occasionally drop or add one component
    if r < 0.05 and q["rw_faults"]:
        q["rw_faults"].pop(int(rng.integers(len(q["rw_faults"]))))
    elif r < 0.10 and len(q["rw_faults"]) < 2:
        free = [w for w in range(4) if w not in {f["wheel"] for f in q["rw_faults"]}]
        q["rw_faults"].append({"wheel": int(rng.choice(free)), "onset_s": round(float(rng.uniform(0, on_hi)), 1),
                               "type": "torque_derate" if rng.random() < 0.5 else "friction",
                               "severity": round(float(rng.uniform(*R["rw_severity"])), 3)})
    elif r < 0.13:
        q["heater"] = None if q["heater"] else {"onset_s": round(float(rng.uniform(0, on_hi)), 1),
                                                "power_W": round(float(rng.uniform(*R["heater_W"])), 2)}
    elif r < 0.16:
        if q["torque_leak"]:
            q["torque_leak"] = None
        else:
            ax = rng.normal(size=3); ax /= np.linalg.norm(ax)
            q["torque_leak"] = {"onset_s": round(float(rng.uniform(0, on_hi)), 1),
                                "mag_Nm": float(f"{rng.uniform(*R['leak_Nm']):.3e}"), "axis": [round(float(a), 4) for a in ax]}
    return validate(q, rng)[0]


def run(seed, n, workers):
    if not satfix_landed():
        sys.exit("ff_sim.py still has the cumulative wheel_saturation rule; refusing to run")
    b = json.load(open(os.path.join(OUT, f"oneshot_seed{seed}_bank.json")))
    bank = b["bank"]
    jobs, src = [], {}
    for i in range(n):
        if i < len(bank):
            p = bank[i]["params"]; src[i] = ("bank", i)
        else:
            rng = np.random.default_rng([33, seed, i])
            k = int(rng.integers(len(bank))); p = mutate(bank[k]["params"], rng); src[i] = ("mutation", k)
        jobs.append((i, seed, p))
    out = os.path.join(OUT, f"oneshot_seed{seed}.jsonl")
    done = set()
    if os.path.exists(out):
        good = [l for l in open(out) if l.strip().endswith("}")]
        open(out, "w").writelines(good)
        done = {json.loads(l)["id"] for l in good}
    todo = [j for j in jobs if j[0] not in done]
    print(f"oneshot seed {seed}: {len(done)} done, {len(todo)} to run (bank {len(bank)})", flush=True)
    t0 = time.perf_counter()
    with open(out, "a") as f, Pool(workers) as pool:
        for k, res in enumerate(pool.imap(_run, todo)):
            res["source"] = "oneshot_" + src[res["id"]][0]; res["parent"] = src[res["id"]][1]
            f.write(json.dumps(res) + "\n"); f.flush()
            if (k + 1) % 25 == 0:
                print(f"  {k+1}/{len(todo)} {time.perf_counter()-t0:.0f}s", flush=True)
    print("done", out, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["bank", "run"])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--bank", type=int, default=40)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    make_bank(a.seed, a.bank) if a.mode == "bank" else run(a.seed, a.n, a.workers)
