"""CMA-ES baseline over the FaultForge fault space (same space as random / Muse search).

  python src/cmaes_search.py --seed 0 --budget 300 --popsize 10 --workers 3  -> data/cmp/cmaes_seed0.jsonl

Mixed encoding: a fixed 27-dim vector z in [0,1]^27 (CMA-ES with box bounds) decodes to a scenario:
  z[0] beta (linear in range), z[1] f0
  per wheel w=0..3 (4 dims each): gate g_w, onset, type (<0.5 torque_derate, else friction), severity
      wheel w is faulted iff g_w > 0.5; if more than 2 gates are open only the 2 largest are kept
      (random search allows <=2 RW faults on distinct wheels)
  heater (3): gate > 0.5 -> present, onset, power
  leak (6):   gate > 0.5 -> present, onset, magnitude, axis = 3 dims mapped to [-1,1] then normalized
Discrete choices are thus relaxed by thresholding continuous genes (the search sees a piecewise-constant
landscape in those genes, smooth in the magnitudes/timings).

Objective (minimized; <= 0 means a constraint was crossed), from the near-miss margins in each result:
  battery  = battery_margin / 0.45                     (0.45 = start SoC 0.65 - floor 0.20)
  attitude = 1 - att_dur_ratio                          (out-of-bound stretch / 1200 s limit)
  wheels   = 1 - sat_dur_ratio      if wheel_speed_ratio >= 1  (already at the saturation threshold)
             2 - wheel_speed_ratio  otherwise                  (distance to the threshold)
  f = min(battery, attitude, wheels)
On cma's own termination criteria the run restarts from a fresh random mean (budget counted throughout).
"""
import argparse
import json
import os
import sys
import time
from multiprocessing import Pool

import cma
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
from search import T_end, _run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIM = 2 + 16 + 3 + 6


def _lin(u, lo, hi):
    return lo + float(np.clip(u, 0, 1)) * (hi - lo)


def decode(z):
    R, Te = ff_sim.RANGES, T_end()
    z = np.clip(np.asarray(z, float), 0, 1)
    on = lambda u: round(_lin(u, 0, R["onset_frac"][1] * Te), 1)
    p = {"orbit": {"beta_deg": round(_lin(z[0], *R["beta_deg"]), 2), "f0_deg": round(_lin(z[1], 0, 360) % 360, 2)},
         "rw_faults": [], "heater": None, "torque_leak": None}
    gates = [(z[2 + 4 * w], w) for w in range(4) if z[2 + 4 * w] > 0.5]
    for g, w in sorted(gates, reverse=True)[:2]:
        b = 2 + 4 * w
        p["rw_faults"].append({"wheel": w, "onset_s": on(z[b + 1]),
                               "type": "torque_derate" if z[b + 2] < 0.5 else "friction",
                               "severity": round(_lin(z[b + 3], *R["rw_severity"]), 3)})
    p["rw_faults"].sort(key=lambda f: f["wheel"])
    if z[18] > 0.5:
        p["heater"] = {"onset_s": on(z[19]), "power_W": round(_lin(z[20], *R["heater_W"]), 2)}
    if z[21] > 0.5:
        ax = 2 * z[24:27] - 1
        if np.linalg.norm(ax) < 1e-6:
            ax = np.array([0, 0, 1.0])
        ax = ax / np.linalg.norm(ax)
        p["torque_leak"] = {"onset_s": on(z[22]), "mag_Nm": float(f"{_lin(z[23], *R['leak_Nm']):.3e}"),
                            "axis": [round(float(a), 4) for a in ax]}
    return p


def closeness(r):
    m = r["margins"]
    bat = m["battery_margin"] / 0.45
    att = 1.0 - m["att_dur_ratio"]
    whl = 1.0 - m["sat_dur_ratio"] if m["wheel_speed_ratio"] >= 1.0 else 2.0 - m["wheel_speed_ratio"]
    return float(min(bat, att, whl))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=int, default=300)
    ap.add_argument("--popsize", type=int, default=10)
    ap.add_argument("--sigma0", type=float, default=0.3)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--policy", default="v1", help="policy under test (v1 | v2 | policy json path)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    os.environ["FF_POLICY"] = a.policy
    out = a.out or os.path.join(ROOT, "data", "cmp", f"cmaes_seed{a.seed}.jsonl")
    rng = np.random.default_rng(20_000 + a.seed)
    rows, t0, restart, gen = [], time.perf_counter(), 0, 0
    with open(out, "w") as fo, Pool(a.workers) as pool:
        while len(rows) < a.budget:
            x0 = 0.5 * np.ones(DIM) if restart == 0 else rng.uniform(0.2, 0.8, DIM)
            es = cma.CMAEvolutionStrategy(x0, a.sigma0, {"bounds": [0, 1], "popsize": a.popsize, "verbose": -9,
                                                         "seed": int(a.seed * 1000 + restart + 1)})
            while not es.stop() and len(rows) < a.budget:
                X = es.ask()
                n = min(len(X), a.budget - len(rows))
                jobs = [(len(rows) + k, None, decode(X[k])) for k in range(n)]
                res = pool.map(_run, jobs)
                fs = []
                for r, x in zip(res, X[:n]):
                    r["seed"] = a.seed; r["gen"] = gen; r["restart"] = restart
                    r["objective"] = closeness(r); r["z"] = [round(float(v), 5) for v in x]
                    rows.append(r); fo.write(json.dumps(r) + "\n"); fs.append(r["objective"])
                fo.flush()
                if n == len(X):
                    es.tell(X, fs)
                nv = sum(r["violated"] for r in rows)
                print(f"seed {a.seed} restart {restart} gen {gen}: {len(rows)}/{a.budget} sims, {nv} viol, "
                      f"best f {min(fs):.3f}, {time.perf_counter()-t0:.0f}s", flush=True)
                gen += 1
            restart += 1
    print("wrote", out)


if __name__ == "__main__":
    main()
