# FaultForge

FaultForge searches for **multi-fault combinations** in a spacecraft simulation that make an existing
rule-based recovery (safe-mode/FDIR) policy violate explicit safety constraints, then **minimizes**
each violation to a small, reproducible counterexample with a one-command replay.

This repo has a Basilisk power + attitude CubeSat harness, a rule-based policy, seeded random/grid search,
a greedy minimizer and replay, plus a **Muse Spark-guided search** (`src/llm_search.py`) compared against
random search at equal simulation budget (results below).

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
src/llm_search.py  Muse Spark-guided search (api.meta.ai/v1, model muse-spark-1.3)
src/compare.py     equal-budget Muse vs random: minimize every violation, dedupe patterns, summary + plot
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

## Results: Muse-guided vs random search (equal sim budget)

```bash
export MUSE_API_KEY=...                                    # never committed
python src/llm_search.py --seed 0 --budget 300 --batch 8   # -> data/cmp/muse_seed0.jsonl (+ _calls.jsonl LLM log)
python src/search.py random --n 300 --seed 0 data/cmp/random_seed0.jsonl
python src/compare.py --workers 8                          # -> data/cmp/summary.json, data/cmp/minimized.jsonl,
                                                           #    plots/muse_vs_random.png
```

Setup: `muse-spark-1.3` via the OpenAI-compatible `POST https://api.meta.ai/v1/chat/completions` (JSON mode).
Each round the model gets the fault schema/ranges, the plant + policy description, discovered violation
signatures, and a compacted history (recent violations, top-25 near-misses by margin, last batch) with
near-miss margins (`margins` in every sim result: battery_margin, att_err_ratio, att_dur_ratio,
wheel_speed_ratio, sat_dur_ratio). It returns 8 scenarios per call; they are clamped to exactly the space
random search samples (<=2 RW faults on distinct wheels, <=1 heater, <=1 leak). Every violation from either
arm is minimized (`minimize.py`) and re-run with the policy disabled; *policy-induced* = the minimized
target violation does not occur without the policy. Fine pattern = violation <- faults with wheel index /
dominant leak axis; coarse = fault kinds only.

| seed | arm | sims | violations/sim | sims to 1st | unique fine | unique coarse | policy-induced fine |
|---|---|---|---|---|---|---|---|
| 0 | Muse | 232* | 0.388 (90) | 4 | 40 | 19 | 28 |
| 0 | random | 232* | 0.009 (2) | 10 | 2 | 1 | 0 |
| 1 | Muse | 300 | 0.317 (95) | 3 | 43 | 20 | 31 |
| 1 | random | 300 | 0.007 (2) | 15 | 2 | 2 | 2 |
| 2 | Muse | 300 | 0.313 (94) | 10 | 34 | 17 | 26 |
| 2 | random | 300 | 0.003 (1) | 166 | 1 | 1 | 0 |
| mean | Muse | | **0.339** | **5.7** | **39.0** | **18.7** | **28.3** |
| mean | random | | 0.006 | 63.7 | 1.7 | 1.3 | 0.7 |

\* seed 0 Muse was stopped at 232 sims to stay inside the hackathon API call cap; random seed 0 is truncated
to its first 232 runs (runs are i.i.d. per id), so the budget is still equal.

Union over seeds: Muse 71 fine / 26 coarse patterns (53 fine policy-induced); random 5 fine / 3 coarse (2
policy-induced). 2 fine patterns were found by both; 69 only by Muse; 3 only by random. Muse also found
`battery_floor` violations (10 runs), which random never hit in 900 + 576 grid runs.
LLM cost: 105 rounds, ~1.55M tokens (~0.89M prompt, ~0.68M completion, of which ~0.55M reasoning),
mean latency ~31 s/call (p95 ~45 s). Plot: `plots/muse_vs_random.png`.

Caveats
- Muse is **white-box**: it is told the policy thresholds and the one-isolation FDIR rule; random search is
  policy-agnostic. The comparison measures "model + spec" vs blind sampling, not vs a tuned optimizer
  (no CMA-ES/BO baseline yet).
- Many Muse finds are "beyond design" (81/279 minimized cases have >= 2 near-dead wheels, a double fault a
  single-fault-tolerant 4-wheel design is not required to survive); ~54 runs repeat one known single-fault
  weakness (a ~1.1 uNm Z leak saturating wheel 2 with no momentum dumping). Fine patterns over-count
  mechanisms (wheel index permutations); coarse counts are the conservative number.
- "Policy-induced" is target-specific: without the policy some cases fail a *different* constraint.
- The provider content filter intermittently rejected prompts (HTTP 400 `content_policy_violation`; an early
  wording with the word "exploitation" triggered it reliably). 6 rounds fell back to random scenarios
  (48 sims, counted in the Muse arm's budget; 2 of them violated).
- Same simplifications as above (static Sun, 5 s policy steps, no momentum dumping, no thermal/sensor faults).
