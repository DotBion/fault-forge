"""Replay stored scenarios on a policy without new LLM calls (paired comparison).
  python src/repair_replay.py --policy v3 --from v2   -> data/repair/v3/replay_from_v2.json
Re-runs (a) every scenario of data/repair/<from>/muse_seed1.jsonl and (b) every reproducing minimized counterexample
in data/repair/<from>/minimized.jsonl on --policy, and counts violating runs / fixed / new."""
import argparse, json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__))
import ff_sim
from repair import REP, out_of_scope


def _run(job):
    k, p, pol = job
    r = ff_sim.run_scenario(p, telemetry=False, policy=ff_sim.get_policy(pol))
    return k, r["violations"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--policy", default="v3"); ap.add_argument("--from", dest="src", default="v2")
    ap.add_argument("--workers", type=int, default=8); a = ap.parse_args()
    runs = [json.loads(l) for l in open(os.path.join(REP, a.src, "muse_seed1.jsonl"))]
    mins = [json.loads(l) for l in open(os.path.join(REP, a.src, "minimized.jsonl"))]
    mins = [m for m in mins if m["reproduces"]]
    jobs = [(f"run_{r['id']}", r["params"], a.policy) for r in runs] + [(f"min_{m['key']}", m["minimized"], a.policy) for m in mins]
    with Pool(a.workers) as pool:
        res = dict(pool.imap_unordered(_run, jobs, chunksize=2))
    out = {"policy": a.policy, "from": a.src}
    out["muse_search_scenarios"] = {"n": len(runs), f"{a.src}_violating": sum(bool(r["violations"]) for r in runs),
                                    f"{a.policy}_violating": sum(bool(res[f"run_{r['id']}"]) for r in runs),
                                    "fixed": sum(bool(r["violations"]) and not res[f"run_{r['id']}"] for r in runs),
                                    "new": sum(not r["violations"] and bool(res[f"run_{r['id']}"]) for r in runs)}
    for g, sel in (("minimized_in_scope_policy_induced", lambda m: m["policy_induced"] and not out_of_scope(m["minimized"])),
                   ("minimized_all", lambda m: True)):
        ms = [m for m in mins if sel(m)]
        out[g] = {"n": len(ms), "target_fixed": sum(m["target"] not in res[f"min_{m['key']}"] for m in ms),
                  "clean": sum(not res[f"min_{m['key']}"] for m in ms)}
    os.makedirs(os.path.join(REP, a.policy), exist_ok=True)
    json.dump(out, open(os.path.join(REP, a.policy, f"replay_from_{a.src}.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
