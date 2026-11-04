"""Root-cause classification of policy-induced counterexamples by targeted policy ablations (fixed sat rule).

  python src/defects.py [--workers N]        # all policy-induced, reproducing minimized cases in data/cmp/minimized.jsonl
  python src/defects.py --replay KEY ARM     # replay one minimized case (by key prefix) under one ablation arm, print log

Arms (same faults, same orbit; each changes ONE policy behaviour of v1):
  full        v1 policy
  no_isolate  FDIR detects but never isolates a wheel (suppress_isolation)
  swap        v1 + isolation swap: if a wheel is clearly worse than the already-isolated one, swap them (lifts the
              one-isolation lock-in without disabling isolation)
  no_safe     attitude- and SoC-triggered SAFE mode (sun-pointing) disabled; FDIR unchanged
  off         policy disabled entirely
Writes data/satfix/defects.json.
"""
import argparse
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
from compare import out_of_scope  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "satfix", "defects.json")
P = ff_sim.POLICY
ARMS = {
    "full": dict(policy=P),
    "no_isolate": dict(policy={**P, "suppress_isolation": True}),
    "swap": dict(policy={**P, "isolation_swap": True}),
    "no_safe": dict(policy={**P, "att_safe_deg": 1e9, "soc_shed": -1.0}),
    "off": dict(policy=P, policy_enabled=False),
}


def run(params, arm):
    r = ff_sim.run_scenario(params, telemetry=False, **ARMS[arm])
    return {"violations": r["violations"], "isolated": r["isolated_wheels"], "final_mode": r["final_mode"],
            "max_att_deg": round(r["max_att_err_after_grace_deg"], 1), "min_soc": round(r["min_soc"], 3),
            "log": [(t, m) for t, m in r["policy_log"] if "POLICY" in m or "FAULT" in m]}


def _job(m):
    out = {a: run(m["minimized"], a) for a in ARMS}
    return m["key"], out


def classify(m, R):
    tgt = m["target"]
    bad = {a: tgt in R[a]["violations"] for a in R}
    faults = m["minimized"]["rw_faults"]
    iso = R["full"]["isolated"]
    faulty = sorted({f["wheel"] for f in faults})
    if bad["no_isolate"] and bad["no_safe"]:
        return "other (needs both / neither ablation)"
    if not bad["no_isolate"]:
        if len(faulty) >= 2 and iso and not bad["swap"]:
            return "D1 isolation lock-in"
        if len(faulty) >= 2 and iso and set(iso) <= set(faulty):
            # isolated a faulty wheel first; swap does not rescue
            sev = {f["wheel"]: f["severity"] for f in faults}
            return "D1 isolation lock-in" if min(sev[i] for i in iso) < max(sev.values()) else "D2 isolation removes needed wheel"
        return "D2 isolation removes needed wheel"
    return "D3 safe-mode induced"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--replay", nargs=2, metavar=("KEY", "ARM"))
    a = ap.parse_args()
    cache = {}
    for l in open(os.path.join(ROOT, "data", "cmp", "minimized.jsonl")):
        d = json.loads(l); cache[d["key"]] = d
    if a.replay:
        k = [x for x in cache if x.startswith(a.replay[0])][0]
        r = run(cache[k]["minimized"], a.replay[1])
        print(json.dumps(cache[k]["minimized"]))
        print(a.replay[1], r["violations"], "isolated", r["isolated"], "final", r["final_mode"], "max_att", r["max_att_deg"])
        for t, msg in r["log"]:
            print(f"  t={t:7.0f}s  {msg}")
        return
    S = "wheel_saturation"   # skip legacy-rule cache entries that compare.py would recompute
    ms = [m for m in cache.values() if m.get("sat_rule") == "consecutive"
          or (m["target"] != S and S not in m["violations"] and S not in m.get("violations_no_policy", {}))]
    ms = [m for m in ms if m["reproduces"] and m["policy_induced"] and not out_of_scope(m)]
    done = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [m for m in ms if m["key"] not in done or done[m["key"]].get("minimized") != m["minimized"]]
    print(f"{len(ms)} policy-induced in-scope cases, {len(todo)} to run", flush=True)
    with Pool(a.workers) as pool:
        for i, (k, R) in enumerate(pool.imap_unordered(_job, todo)):
            done[k] = {"target": cache[k]["target"], "pattern": cache[k]["pattern_fine"], "minimized": cache[k]["minimized"],
                       "arms": R}
            if (i + 1) % 10 == 0:
                json.dump(done, open(OUT, "w")); print(f"  {i+1}/{len(todo)}", flush=True)
    keep = {m["key"] for m in ms}
    done = {k: d for k, d in done.items() if k in keep}
    for k, d in done.items():
        d["class"] = classify(cache[k], d["arms"])
    json.dump(done, open(OUT, "w"), indent=1)
    from collections import Counter
    print(Counter(d["class"] for d in done.values()))


if __name__ == "__main__":
    main()
