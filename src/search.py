"""Seeded random-search and grid-search baselines over FaultForge fault parameters.

  python src/search.py random --n 300 --seed 0 --workers 6      -> data/random_seed0.jsonl
  python src/search.py grid --workers 6                         -> data/grid.jsonl
  python src/search.py summarize data/random_seed0.jsonl

Every line of the jsonl holds {id, seed, params, violations, ...}, so any run replays with
  python src/replay.py data/random_seed0.jsonl <id>
"""
import argparse
import itertools
import json
import math
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def T_end():
    mu = 3.986004415e14
    a = ff_sim.R_EARTH_M + ff_sim.CFG["alt_km"] * 1e3
    return ff_sim.CFG["n_orbits"] * 2 * math.pi * math.sqrt(a ** 3 / mu)


def sample_params(rng):
    R = ff_sim.RANGES
    Te = T_end()
    onset = lambda: round(float(rng.uniform(*R["onset_frac"]) * Te), 1)
    p = {"orbit": {"beta_deg": round(float(rng.uniform(*R["beta_deg"])), 2),
                   "f0_deg": round(float(rng.uniform(*R["f0_deg"])), 2)},
         "rw_faults": [], "heater": None, "torque_leak": None}
    n_rw = int(rng.choice([0, 1, 2], p=[0.4, 0.45, 0.15]))
    wheels = rng.choice(4, size=n_rw, replace=False)
    for w in wheels:
        p["rw_faults"].append({"wheel": int(w), "onset_s": onset(),
                               "type": "torque_derate" if rng.random() < 0.6 else "friction",
                               "severity": round(float(rng.uniform(*R["rw_severity"])), 3)})
    if rng.random() < 0.5:
        p["heater"] = {"onset_s": onset(), "power_W": round(float(rng.uniform(*R["heater_W"])), 2)}
    if rng.random() < 0.4:
        ax = rng.normal(size=3); ax /= np.linalg.norm(ax)
        p["torque_leak"] = {"onset_s": onset(), "mag_Nm": float(f"{rng.uniform(*R['leak_Nm']):.3e}"),
                            "axis": [round(float(a), 4) for a in ax]}
    return p


def n_faults(p):
    return len(p["rw_faults"]) + (p["heater"] is not None) + (p["torque_leak"] is not None)


def _run(job):
    rid, seed, params = job
    r = ff_sim.run_scenario(params, telemetry=False)
    r.pop("policy_log", None)
    return {"id": rid, "seed": seed, **r}


def run_jobs(jobs, out, workers):
    t0 = time.perf_counter()
    with open(out, "w") as f, Pool(workers) as pool:
        for k, res in enumerate(pool.imap(_run, jobs)):
            f.write(json.dumps(res) + "\n"); f.flush()
            if (k + 1) % 25 == 0:
                print(f"  {k+1}/{len(jobs)} done, {time.perf_counter()-t0:.0f}s", flush=True)
    print(f"wrote {out} ({len(jobs)} runs, wall {time.perf_counter()-t0:.1f}s with {workers} workers)")


def grid_jobs():
    """Systematic search: every single fault at 2 severities x 3 onsets, on a 3x3 orbit grid,
    plus nominal (no-fault) runs. Pairs are left to the random search (combinatorial blow-up)."""
    Te = T_end()
    onsets = [round(f * Te, 1) for f in (0.0, 0.3, 0.6)]
    singles = [{"rw_faults": [], "heater": None, "torque_leak": None}]
    for w, typ, sev, on in itertools.product(range(4), ["torque_derate", "friction"], [0.5, 1.0], onsets):
        singles.append({"rw_faults": [{"wheel": w, "onset_s": on, "type": typ, "severity": sev}],
                        "heater": None, "torque_leak": None})
    for pw, on in itertools.product([3.0, 6.0], onsets):
        singles.append({"rw_faults": [], "heater": {"onset_s": on, "power_W": pw}, "torque_leak": None})
    for ax, on in itertools.product([[1, 0, 0], [0, 1, 0], [0, 0, 1]], onsets):
        singles.append({"rw_faults": [], "heater": None, "torque_leak": {"onset_s": on, "mag_Nm": 1.5e-6, "axis": ax}})
    jobs = []
    for (b, f0), s in itertools.product(itertools.product([5.0, 35.0, 65.0], [0.0, 120.0, 240.0]), singles):
        jobs.append((len(jobs), None, {"orbit": {"beta_deg": b, "f0_deg": f0}, **json.loads(json.dumps(s))}))
    return jobs


def summarize(path):
    rows = [json.loads(l) for l in open(path)]
    n = len(rows)
    v = [r for r in rows if r["violated"]]
    walls = np.array([r["wall_s"] for r in rows])
    print(f"{path}: {n} runs, {len(v)} violating ({100*len(v)/max(n,1):.1f}%)")
    print(f"  wall time per run (single process, inside worker): mean {walls.mean():.2f}s, "
          f"median {np.median(walls):.2f}s, max {walls.max():.2f}s; sim time per run {rows[0]['sim_time_s']:.0f}s")
    types = {}
    for r in v:
        key = "+".join(sorted(r["violations"]))
        types[key] = types.get(key, 0) + 1
    print("  violation types:", types)
    by_nf = {}
    for r in rows:
        k = n_faults(r["params"]); a = by_nf.setdefault(k, [0, 0]); a[0] += 1; a[1] += r["violated"]
    print("  by #faults injected: " + ", ".join(f"{k} faults: {b}/{a}" for k, (a, b) in sorted(by_nf.items())))
    # signature: which fault kinds were present
    sig = {}
    for r in v:
        p = r["params"]
        kinds = sorted([f"rw_{f['type']}" for f in p["rw_faults"]] + (["heater"] if p["heater"] else [])
                       + (["leak"] if p["torque_leak"] else []))
        k = ",".join(kinds) or "none"; sig[k] = sig.get(k, 0) + 1
    print("  violating runs by injected-fault signature:", dict(sorted(sig.items(), key=lambda x: -x[1])))
    print("  violating ids:", [r["id"] for r in v])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["random", "grid", "summarize"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    if a.mode == "summarize":
        summarize(a.path); return
    if a.mode == "random":
        # per-run seed derived from master seed -> each run's params regenerate independently
        jobs = []
        for i in range(a.n):
            s = a.seed * 100000 + i
            jobs.append((i, s, sample_params(np.random.default_rng(s))))
        out = a.path or os.path.join(ROOT, "data", f"random_seed{a.seed}.jsonl")
    else:
        jobs = grid_jobs()
        out = a.path or os.path.join(ROOT, "data", "grid.jsonl")
    print(f"{a.mode}: {len(jobs)} runs")
    run_jobs(jobs, out, a.workers)
    summarize(out)


if __name__ == "__main__":
    main()
