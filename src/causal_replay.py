"""Surgical causal replay: is the WHEEL-ISOLATION decision (not the policy as a whole) what causes the failure?

  python src/causal_replay.py                       # headline case a6e8087b7a52c977 (minimized + original search run)
  python src/causal_replay.py --params FILE.json    # any params JSON ({"params": ...} or bare params)
  make causal                                       # same as the first line
  python src/causal_replay.py --sweep               # + 24-case neighbourhood sweep (severity x onset x beta)

Three arms, same faults, same orbit, fixed (consecutive) wheel_saturation rule:
  full        - v1 policy as flown in all experiments
  no_isolate  - v1 policy with ONLY the FDIR wheel-isolation action suppressed (policy key suppress_isolation=True):
                the residual detector still runs and logs "would be isolated"; safe-mode entry/exit, sun-pointing,
                payload shedding, SoC logic are unchanged
  off         - policy disabled entirely (no FDIR, no safe mode)
Writes data/satfix/causal_replay.json (+ .md when --md).
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "a6e8087b7a52c977"


def metrics(r):
    T = np.array(r["telemetry"]); c = {n: i for i, n in enumerate(r["telemetry_cols"])}
    dt = 10.0  # telemetry every 10 s
    late = T[:, c["t_s"]] > ff_sim.CFG["att_grace_s"]
    return {
        "violations": r["violations"],
        "peak_att_err_after_grace_deg": round(r["max_att_err_after_grace_deg"], 1),
        "time_att_err_gt_30deg_s": float(dt * np.sum(late & (T[:, c["att_err_deg"]] > ff_sim.CFG["att_err_bound_deg"]))),
        "longest_att_err_gt_30deg_run_s": round(r["margins"]["att_dur_ratio"] * ff_sim.CFG["att_err_max_dur_s"]),
        "min_soc": round(r["min_soc"], 3),
        "battery_margin_soc": r["margins"]["battery_margin"],
        "peak_wheel_speed_frac_of_sat_threshold": r["margins"]["wheel_speed_ratio"],
        "longest_consecutive_wheel_sat_s": round(r["margins"]["sat_dur_ratio"] * ff_sim.CFG["sat_max_dur_s"]),
        "time_in_safe_mode_s": float(dt * np.sum(T[:, c["safe_mode"]] > 0.5)),
        "final_mode": r["final_mode"],
        "isolated_wheels_at_end": r["isolated_wheels"],
        "policy_actions": r["n_policy_actions"],
        "policy_log": [[t, m] for t, m in r["policy_log"]],
    }


def run_case(p):
    pol = ff_sim.get_policy("v1")
    arms = {"full": dict(policy=pol), "no_isolate": dict(policy={**pol, "suppress_isolation": True}),
            "off": dict(policy=pol, policy_enabled=False)}
    return {k: metrics(ff_sim.run_scenario(p, telemetry=True, **kw)) for k, kw in arms.items()}


def _sweep_job(job):
    sev, onset1, beta = job
    p = json.loads(json.dumps(headline_params()[f"{KEY} minimized (demo case)"]))
    p["orbit"]["beta_deg"] = beta
    p["rw_faults"][0]["severity"] = sev
    p["rw_faults"][1]["onset_s"] = onset1
    pol = ff_sim.get_policy("v1")
    out = {}
    for k, kw in {"full": dict(policy=pol), "no_isolate": dict(policy={**pol, "suppress_isolation": True}),
                  "off": dict(policy=pol, policy_enabled=False)}.items():
        r = ff_sim.run_scenario(p, telemetry=False, **kw)
        out[k] = sorted(r["violations"])
    return {"rw0_friction_sev": sev, "rw1_derate_onset_s": onset1, "beta_deg": beta, **out}


def sweep(workers):
    """Neighbourhood of the headline case: is 'isolation causes the loss' robust or a knife-edge?"""
    from multiprocessing import Pool
    jobs = [(s, o, b) for s in (0.15, 0.2, 0.3, 0.5) for o in (305.0, 505.0, 1005.0) for b in (45.0, 65.0)]
    with Pool(workers) as pool:
        rows = pool.map(_sweep_job, jobs)
    return rows


def headline_params():
    mn = next(json.loads(l) for l in open(os.path.join(ROOT, "data/cmp/minimized.jsonl")) if json.loads(l)["key"] == KEY)
    orig = next(json.loads(l) for l in open(os.path.join(ROOT, "data/cmp/muse_seed1.jsonl")) if json.loads(l)["id"] == 173)
    return {f"{KEY} minimized (demo case)": mn["minimized"], "muse_seed1 run 173 (original search hit)": orig["params"]}


def fmt(cases):
    L = []
    for name, res in cases.items():
        L += [f"### {name}", "", "| metric | full policy | isolation-only suppressed | policy off |", "|---|---|---|---|"]
        for k in ("violations", "peak_att_err_after_grace_deg", "time_att_err_gt_30deg_s", "longest_att_err_gt_30deg_run_s",
                  "min_soc", "peak_wheel_speed_frac_of_sat_threshold", "longest_consecutive_wheel_sat_s",
                  "time_in_safe_mode_s", "final_mode", "isolated_wheels_at_end", "policy_actions"):
            L.append(f"| {k} | " + " | ".join(f"`{json.dumps(res[a][k])}`" for a in ("full", "no_isolate", "off")) + " |")
        L.append("")
        for a in ("full", "no_isolate"):
            L.append(f"Policy log ({a}):")
            L += [f"    t={t:6.0f}s  {m}" for t, m in res[a]["policy_log"] if m.startswith("POLICY")]
            L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--params")
    ap.add_argument("--sweep", action="store_true", help="also run a 24-case neighbourhood sweep (-> causal_sweep.json)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "satfix", "causal_replay.json"))
    a = ap.parse_args()
    if a.params:
        d = json.load(open(a.params)); cases = {os.path.basename(a.params): d.get("params", d)}
    else:
        cases = headline_params()
    res = {n: run_case(p) for n, p in cases.items()}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"sat_rule": ff_sim.CFG["sat_rule"], "params": cases, "results": res}, open(a.out, "w"), indent=1)
    print(fmt(res))
    if a.sweep:
        rows = sweep(a.workers)
        json.dump(rows, open(os.path.join(os.path.dirname(a.out), "causal_sweep.json"), "w"), indent=1)
        for r in rows:
            print(r)
