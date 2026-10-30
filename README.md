# FaultForge

FaultForge searches for **multi-fault combinations** in a spacecraft simulation that make an existing
rule-based recovery (safe-mode/FDIR) policy violate explicit safety constraints, then **minimizes**
each violation to a small, reproducible counterexample with a one-command replay.

This repo is the feasibility baseline: a Basilisk power + attitude CubeSat harness, a rule-based policy,
seeded random/grid search, a greedy minimizer and replay. No LLM is integrated yet; the next step is a
model-guided search compared against random search at equal simulation budget.

## Setup

Python 3.13 on Linux x86_64 (tested with 3.13.5). Basilisk installs as a prebuilt pip wheel, no build needed.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt     # bsk==2.12.1, numpy, matplotlib, pandas
```

Notes / gotchas
- The `bsk` wheel does **not** ship the `examples/` folder. `src/power_demo.py` is a copy of the stock
  `scenarioPowerDemo.py` (Basilisk, ISC license) with CSV/PNG export added.
- On first use Basilisk downloads SPICE kernels to `~/.cache/bsk_support_data` (needed only by the power demo;
  the FaultForge harness uses a static Sun message and no SPICE).
- `reactionWheelStateEffector` default `omegaLimitCycle` (1e-4 rad/s) makes Coulomb friction numerically stiff
  under RK4 at useful step sizes; the harness sets it to 4 rad/s and uses dt = 0.1 s.
- In Basilisk RW config, `u_max <= 0` means *unlimited* torque; a failed wheel is modelled with `u_max = 1e-9`.

## Layout

```
src/ff_sim.py      scenario, fault injection, policy, safety constraints  (CFG / POLICY / RANGES at top)
src/search.py      random | grid | summarize
src/minimize.py    greedy fault dropping + magnitude bisection
src/replay.py      one-command replay -> plot + CSV, checks it matches the recorded run
src/power_demo.py  stock scenarioPowerDemo + CSV/PNG export
data/              search results (.jsonl), minimal counterexamples (minimal_*.json), replay CSVs
plots/             replay and demo plots
```

## Run

```bash
python src/power_demo.py                                   # -> data/power_demo.csv, plots/power_demo.png
python src/replay.py --nominal                             # fault-free 2-orbit run
python src/search.py random --n 300 --seed 0 --workers 6   # -> data/random_seed0.jsonl
python src/search.py grid --workers 6                      # 576 single-fault runs -> data/grid.jsonl
python src/search.py summarize data/random_seed0.jsonl
python src/minimize.py data/random_seed1.jsonl 218         # -> data/minimal_random_seed1_218.json
```

## Replay a failure

```bash
python src/replay.py data/minimal_random_seed1_218.json             # minimal counterexample
python src/replay.py data/minimal_random_seed1_218.json --no-policy # same faults, policy disabled
python src/replay.py data/random_seed0.jsonl 9                      # any run from a result file by id
```

Replay prints the fault/policy event log, re-checks violations against the recorded result and writes
`plots/replay_<tag>.png` and `data/replay_<tag>.csv`. Runs are deterministic (per-run seed = seed*100000 + id).

## Scenario (what is modelled)

- 10 kg 6U-like CubeSat, 500 km circular orbit, 2 orbits (11355 s), gravity gradient, small constant disturbance torque.
- 4 reaction wheels (BCT RWP015: 4 mNm, 15 mNms, 6000 rpm), pyramid-ish layout x, y, z, (1,1,1)/sqrt(3).
- Body-fixed panel on +X_B (0.07 m^2, 29%), 30 Wh battery (start 65% SoC), bus 3 W, payload 4 W, wheel power.
  Attitude couples to power: nominal mode is nadir-pointing (panel to zenith); SAFE mode sun-points the panel.
- Fault parameters: orbit beta angle and start phase (eclipse timing), RW torque derate / failure, RW friction
  increase, stuck-on heater (1-6 W), external torque leak (0.3-1.5 uNm), each with an onset time.
- Policy: SoC < 40% -> SAFE (payload off, sun-point); attitude error > 15 deg for 120 s -> SAFE; return to
  NOMINAL at SoC > 70% after >= 600 s; FDIR isolates a wheel whose torque residual stays high for 3 chunks,
  only while > 3 wheels are available. No momentum dumping.
- Safety constraints: SoC >= 20%; attitude error <= 30 deg (not sustained > 1200 s after a 900 s grace);
  no available wheel at >= 98% max speed for > 60 s.

## Simplifications

Static Sun direction (1 AU, +X_N); sun-pointing uses truth sun vector from simpleNav (also in eclipse);
faults and policy act on 5 s chunk boundaries; FDIR residual from wheel speed derivative vs commanded torque;
no magnetorquers/momentum dumping, thermal model, or sensor faults; generic constant loads.
