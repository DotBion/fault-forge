"""Rank Muse-found, policy-induced, minimized counterexamples by visual clarity (for demo video v2).
  python src/video_candidates.py --workers 2   -> data/video_candidates_runs.jsonl (resumable)"""
import argparse, collections, glob, hashlib, json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "video_candidates_runs.jsonl")


def phash(p):
    return hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]


def _run(d):
    r = ff_sim.run_scenario(d["minimized"], telemetry=False)
    n = ff_sim.run_scenario(d["minimized"], telemetry=False, policy_enabled=False)
    return {"key": d["key"], "violations": r["violations"], "margins": r["margins"], "min_soc": r["min_soc"],
            "max_att_err_deg": r["max_att_err_after_grace_deg"], "policy_log": [f"t={t:.0f}s {m}" for t, m in r["policy_log"]],
            "nopol_violations": n["violations"], "nopol_margins": n["margins"], "nopol_min_soc": n["min_soc"],
            "nopol_max_att_err_deg": n["max_att_err_after_grace_deg"]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=2); a = ap.parse_args()
    src = collections.defaultdict(list)
    for f in glob.glob(os.path.join(ROOT, "data", "cmp", "*_seed*.jsonl")):
        if "calls" in f:
            continue
        arm = os.path.basename(f)[:-6]
        for l in open(f):
            r = json.loads(l)
            if r["violated"]:
                src[phash(r["params"])].append(f"{arm}_{r['id']}")
    mins = [json.loads(l) for l in open(os.path.join(ROOT, "data", "cmp", "minimized.jsonl"))]
    cand = [d for d in mins if d["reproduces"] and d["policy_induced"] and src[d["key"]]
            and all(s.startswith("muse") for s in src[d["key"]])
            and sum(1 for f in d["minimized"]["rw_faults"] if f["type"] == "torque_derate" and f["severity"] >= 0.9) < 2]
    done = {json.loads(l)["key"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [d for d in cand if d["key"] not in done]
    print(len(cand), "candidates,", len(todo), "to run", flush=True)
    with open(OUT, "a") as f, Pool(a.workers) as pool:
        for r in pool.imap_unordered(_run, todo):
            r["source_runs"] = src[r["key"]]; f.write(json.dumps(r) + "\n"); f.flush()


if __name__ == "__main__":
    main()
