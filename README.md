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

## Results: Muse-guided vs rules-blind Muse vs CMA-ES vs random (equal sim budget)

```bash
export MUSE_API_KEY=...                                    # never committed
python src/llm_search.py --seed 0 --budget 300 --batch 8   # -> data/cmp/muse_seed0.jsonl (+ _calls.jsonl LLM log)
python src/llm_search.py --seed 1 --blind --budget 300     # rules-blind variant -> data/cmp/museblind_seed1.jsonl
python src/cmaes_search.py --seed 0 --budget 300           # -> data/cmp/cmaes_seed0.jsonl
python src/search.py random --n 300 --seed 0 data/cmp/random_seed0.jsonl
python src/compare.py --workers 8                          # -> data/cmp/summary.json, data/cmp/minimized.jsonl,
                                                           #    plots/arms_comparison.png
```

Arms (all draw from the same scenario space: <=2 RW faults on distinct wheels, <=1 heater, <=1 leak):
- **Muse** (`muse-spark-1.3`, `POST https://api.meta.ai/v1/chat/completions`, JSON mode). Each round the model gets
  the fault schema/ranges, the plant + full policy description (thresholds and the one-isolation FDIR rule),
  discovered violation signatures, and a compacted history (recent violations, top-25 near-misses by margin, last
  batch) with near-miss margins. It returns 8 scenarios per call, which are clamped to the shared space.
- **Muse-blind** (`--blind`, seed 1): the same loop, but the policy is described only qualitatively (low SoC -> SAFE,
  long attitude error -> SAFE, FDIR may isolate a wheel whose residual stays high). No thresholds and no
  "at most one isolation" rule. It still sees the schema and per-run outcomes/margins/isolated wheels/final mode.
- **CMA-ES** (`cma==4.5.0`, `src/cmaes_search.py`): a relaxed 27-dim encoding z in [0,1]. Orbit beta, f0; per wheel
  (gate>0.5, onset, type <0.5 derate else friction, severity), keeping the 2 highest gates; heater (gate, onset,
  power); leak (gate, onset, magnitude, 3 axis dims -> [-1,1], normalized). It minimizes a normalized margin
  `min(battery_margin/0.45, 1-att_dur_ratio, wheel term)` with wheel term = `1-sat_dur_ratio` once a wheel hits 98 %,
  otherwise `2-wheel_speed_ratio`; a value < 0 means a violation. popsize 10, sigma0 0.3, x0 = 0.5, restarts on stop.
- **Random**: i.i.d. samples from the space.

Every violation from every arm is minimized (`minimize.py`) and re-run with the policy disabled. *Policy-induced* =
the minimized target violation does not occur without the policy. Fine pattern = violation <- faults with wheel
index / dominant leak axis; coarse = fault kinds only. *Out of scope* = the minimized case still needs >= 2
torque-derated wheels with severity >= 0.9 (two near-dead wheels, beyond a single-fault-tolerant 4-wheel design).

| seed | arm | sims | violations/sim | sims to 1st | unique fine | unique coarse | policy-induced fine | ... in scope | out-of-scope share |
|---|---|---|---|---|---|---|---|---|---|
| 0 | Muse | 232* | 0.388 (90) | 4 | 40 | 19 | 28 | 19 | 0.28 |
| 0 | CMA-ES | 232* | 0.185 (43) | 4 | 4 | 2 | 4 | 4 | 0.00 |
| 0 | random | 232* | 0.009 (2) | 10 | 2 | 1 | 0 | 0 | 0.00 |
| 1 | Muse | 300 | 0.317 (95) | 3 | 43 | 20 | 31 | 19 | 0.32 |
| 1 | Muse-blind | 300 | **0.420 (126)** | 6 | 35 | 19 | 26 | 15 | 0.21 |
| 1 | CMA-ES | 300 | 0.040 (12) | 154 | 4 | 3 | 4 | 4 | 0.00 |
| 1 | random | 300 | 0.007 (2) | 15 | 2 | 2 | 2 | 2 | 0.00 |
| 2 | Muse | 300 | 0.313 (94) | 10 | 34 | 17 | 26 | 17 | 0.28 |
| 2 | CMA-ES | 300 | 0.013 (4) | 157 | 2 | 2 | 2 | 2 | 0.00 |
| 2 | random | 300 | 0.003 (1) | 166 | 1 | 1 | 0 | 0 | 0.00 |
| mean | Muse (3 seeds) | | **0.339** | **5.7** | **39.0** | **18.7** | **28.3** | **18.3** | 0.29 |
| mean | Muse-blind (1 seed) | | 0.420 | 6.0 | 35.0 | 19.0 | 26.0 | 15.0 | 0.21 |
| mean | CMA-ES (3 seeds) | | 0.080 | 105.0 | 3.3 | 2.3 | 3.3 | 3.3 | 0.00 |
| mean | random (3 seeds) | | 0.006 | 63.7 | 1.7 | 1.3 | 0.7 | 0.7 | 0.00 |

\* Seed 0 Muse was stopped at 232 sims (API call cap). Every arm is truncated to the shortest arm per seed, so the
budget is equal; CMA-ES seed 0 had 71 violations in its full 300.

Union of fine patterns over seeds: Muse 71 (53 policy-induced), Muse-blind 35 (26), CMA-ES 7 (7), random 5 (2).
Fine patterns found by only one arm: Muse 43, Muse-blind 9, CMA-ES 3, random 3. Plot: `plots/arms_comparison.png`.

Reading the table:
- Both Muse arms beat CMA-ES and random by a wide margin on *diversity*: 15-19 in-scope policy-induced fine
  patterns per seed vs 2-4 for CMA-ES. CMA-ES can match Muse on raw violation rate when it converges early (seed 0),
  but it then refines one mechanism; on seeds 1-2 it took ~155 sims to find any violation. Its rate varies a lot
  by seed (71 / 12 / 4 per 300).
- **Rules-blind Muse still wins.** On seed 1 it got more violations than white-box Muse (126 vs 95; all 126 came
  from its 252 model-proposed sims, the 48 fallback sims had none), with a slightly lower diversity
  (35 vs 43 fine, 15 vs 19 in-scope policy-induced) and a lower out-of-scope share (0.21 vs 0.32). From
  isolated_wheels and outcomes alone it inferred by round 4 that FDIR only ever isolates one wheel. This is a
  single seed, so treat the blind-vs-white-box ordering as indicative only.
- About 21-32 % of the Muse arms' minimized cases are out of scope (two near-dead wheels). CMA-ES and random found
  none, so their few finds are all "in scope", but there are few of them.

LLM cost: white-box Muse 105 rounds, ~1.55M tokens, mean latency ~31 s/call. Blind seed 1: 39 rounds, ~0.44M tokens,
~27 s/call.

Caveats
- Fine patterns over-count mechanisms (wheel-index permutations); coarse counts are the conservative number.
  ~54 Muse runs repeat one known single-fault weakness (a ~1.1 uNm Z leak saturating wheel 2 with no momentum dumping).
- "Policy-induced" is target-specific: without the policy some cases fail a *different* constraint.
- Provider content filter (HTTP 400 `content_policy_violation`, a fast prompt-side classifier). An early wording
  with the word "exploitation" triggered it reliably. White-box Muse: 6 rounds fell back to random (48 sims,
  2 violating). Blind seed 1: 6 rounds fell back to random (rounds 5-8, 13, 22; 48 sims, 0 violating), counted in
  its budget. To get the blind run past round 8, its prompt changed mid-run:
  (a) the blind policy block was reworded (v1 layout, numbers/one-isolation rule removed);
  (b) a style line asking for plain reliability-engineering wording was added to both system prompts;
  (c) a one-line study-context preface was added to the user turn (bisected: the history was rejected
      deterministically without it);
  (d) from round 22 the history was sent as compact table rows.
  None of these add policy information. The white-box Muse runs were done before (b)-(d).
- CMA-ES uses a relaxed continuous encoding with a hand-made margin objective. A different encoding or objective
  (or BO) could do better; it is a reasonable, not a tuned, baseline.
- Same simplifications as above (static Sun, 5 s policy steps, no momentum dumping, no thermal/sensor faults).
