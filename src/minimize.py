"""Delta-debugging style minimization of a failing fault combination.

  python src/minimize.py data/random_seed0.jsonl 17

1) drop faults one at a time (keep the drop if the run still violates the SAME constraint type(s) as
   the original's first violation); repeat until no single drop keeps it failing.
2) relax each remaining fault's magnitude (RW severity, heater W, leak Nm) by bisection toward the
   lower end of its search range, keeping the smallest value that still fails.
Writes data/minimal_<tag>.json (replay with src/replay.py on that file).
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
from replay import load  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N_SIMS = [0]


def fails(p, target):
    N_SIMS[0] += 1
    r = ff_sim.run_scenario(p, telemetry=False)
    return target in r["violations"], r["violations"]


def components(p):
    c = [("rw", i) for i in range(len(p["rw_faults"]))]
    if p["heater"]: c.append(("heater", None))
    if p["torque_leak"]: c.append(("torque_leak", None))
    return c


def drop(p, comp):
    q = copy.deepcopy(p)
    if comp[0] == "rw": q["rw_faults"].pop(comp[1])
    else: q[comp[0]] = None
    return q


def minimize(params, target, log=print):
    cur = copy.deepcopy(params)
    changed = True
    while changed:
        changed = False
        for comp in components(cur):
            q = drop(cur, comp)
            ok, v = fails(q, target)
            log(f"  drop {comp}: {'still fails' if ok else 'passes'} {v}")
            if ok:
                cur, changed = q, True
                break
    R = ff_sim.RANGES
    knobs = [(("rw_faults", i, "severity"), R["rw_severity"][0]) for i in range(len(cur["rw_faults"]))]
    if cur["heater"]: knobs.append((("heater", "power_W"), R["heater_W"][0]))
    if cur["torque_leak"]: knobs.append((("torque_leak", "mag_Nm"), R["leak_Nm"][0]))

    def get(p, path):
        for k in path: p = p[k]
        return p

    def setv(p, path, v):
        for k in path[:-1]: p = p[k]
        p[path[-1]] = v

    for path, lo in knobs:
        hi = get(cur, path)            # known failing
        q = copy.deepcopy(cur); setv(q, path, lo)
        ok, _ = fails(q, target)
        if ok:
            cur = q; log(f"  relax {path}: fails even at range minimum {lo}"); continue
        for _ in range(5):
            mid = (lo + hi) / 2
            q = copy.deepcopy(cur); setv(q, path, float(f"{mid:.4g}"))
            ok, _ = fails(q, target)
            if ok: hi = float(f"{mid:.4g}")
            else: lo = mid
        setv(cur, path, hi); log(f"  relax {path}: smallest failing value found {hi:.4g} (passes at {lo:.4g})")
    return cur


def main():
    path, rid = sys.argv[1], int(sys.argv[2])
    params, rec, tag = load(path, rid)
    first = min(rec, key=rec.get)
    print(f"original violations {rec}; minimizing w.r.t. '{first}'")
    m = minimize(params, first)
    r = ff_sim.run_scenario(m, telemetry=False)
    out = {"source": f"{path}#{rid}", "target_violation": first, "params": m, "violations": r["violations"],
           "n_faults_before": len(components(params)), "n_faults_after": len(components(m)),
           "minimization_sims": N_SIMS[0] + 1,
           "replay": f"python src/replay.py data/minimal_{tag}.json"}
    p = os.path.join(ROOT, "data", f"minimal_{tag}.json")
    json.dump(out, open(p, "w"), indent=1)
    print(json.dumps(out, indent=1)); print("wrote", p)


if __name__ == "__main__":
    main()
