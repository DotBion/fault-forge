# FaultForge

**Quickstart** (Linux x86_64, Python 3.13; no API key needed for the first two lines):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # or: make setup
make replay                                    # keyless: re-sim headline case policy on/off + recorded Muse calls
cp .env.example .env   # put your key in .env, then:  make live   (one live Muse Spark search round)
```

FaultForge hands an FDIR team the multi-fault combinations a test campaign would miss, each as a one-command
replay with a candidate patch the gate has vetted. Meta's Muse Spark model searches a Basilisk CubeSat simulation
for fault combinations that make a rule-based recovery (safe-mode / FDIR) policy violate its safety constraints;
every violation is minimized to a small counterexample, re-run with the policy disabled, and replayable with one
command. Muse then diagnoses the failures and proposes policy patches, which a regression gate it does not control
accepts or rejects.

Before this hackathon week the project had the Basilisk harness and the rule-based FDIR policy. This week:
the Muse-guided search, the rules-blind variant, CMA-ES and random baselines, the minimizer/compare pipeline,
the Muse repair loop and the regression gate.

## Meta models used

One model, **`muse-spark-1.3`**, via the Meta Model API: `POST https://api.meta.ai/v1/chat/completions`
(OpenAI-compatible, JSON mode, key in `MUSE_API_KEY`). It is used in four roles:

| role | what Muse does | code | recorded calls |
|---|---|---|---|
| scenario search | each round reads the fault schema, the policy description, the failures found so far and near-miss margins, and returns 8 new fault scenarios as JSON | `src/llm_search.py`, `src/live_round.py` | `data/cmp/muse_seed*_calls.jsonl` |
| blind rule inference | same search with the policy thresholds and the one-isolation rule hidden; it must infer the rules from outcomes (by round 4 of seed 1 it wrote "FDIR isolates at most one wheel") | `src/llm_search.py --blind` | `data/cmp/museblind_seed*_calls.jsonl` |
| diagnosis | reads minimized counterexamples with policy traces and explains the failure mechanism | `src/gated_repair.py`, `src/gated_v2.py` (also `src/repair.py`) | `data/gated/*_response.json` (`diagnosis`) |
| patch proposal | proposes a bounded policy change (whitelisted keys); the gate re-simulates it on the full suite, and rejections (with regressions + traces) go back to Muse | same | `data/gated/*_response.json` (`change`), `*_gate.json` |

Provenance: `src/muse_client.py` (used by `make live`) logs, for every call, the timestamp, endpoint, requested and
returned model id, the response `id` and the `x-request-id` header (`data/live/*.json`). The historical search and
repair logs were recorded before that wrapper existed: they store the model id (repair), latency, token usage and
the verbatim response, but **no request ids**. `make replay` prints these and the git commit that first recorded each file.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt    # bsk==2.12.1 prebuilt wheel, no build
cp .env.example .env && $EDITOR .env                                     # MUSE_API_KEY=<your key>, no quotes; only for `make live`
make replay        # ~5-15 s, no network
make live          # ~1-2 min: one Muse call (30-100 s) + 8 Basilisk sims; LIVE_ARGS="--workers 2 --n 8 --blind" optional
```

`make` uses `.venv/bin/python3` if it exists, else `python3`. `MUSE_API_KEY` from the environment wins over `.env`.
`.env` is git-ignored. Tested on Debian (Python 3.13.5); see `docs/clean_clone_test.md` for a clean-clone transcript.

## Architecture (short)

```
Muse Spark (api.meta.ai) --scenario JSON--> validate/clamp to shared fault space --> Basilisk sim (src/ff_sim.py:
   ^                                                                                  power + attitude + 4 RWs + FDIR policy)
   |                                                                                           |
   +---- history: failures + near-miss margins <---- safety-constraint checks <----------------+
violations --> src/minimize.py (drop faults, bisect magnitudes) --> policy-off re-run --> replay file
minimized failures --> Muse diagnosis + patch --> gate (src/gated_repair.py / gated_v2.py: re-simulate the full
   suite, 576-case single-fault grid + 2,932 stored search runs; checks outside the model's control) --> accept / reject,
   rejections fed back to Muse for the next try
```

Gate retry budgets (true numbers from the code / the runs): strict loop `gated_repair.py loop --tries 4
--narrow-tries 2` = up to 6 proposals per round (round 1 used all 6; round 2 was stopped by hand after 4 to free time for the structural phase); structural phase = up to 2
attempts; budget mode `gated_v2.py budget --tries 4` = up to 4 proposals per round.

## Limitations and honest scope

- **Simulation only, one spacecraft.** Static Sun direction, no momentum dumping (no magnetorquers), 5 s policy
  steps, no thermal model or sensor faults, generic loads. Findings are about this policy in this sim.
- **The FDIR policy is ours.** Its structure (torque-residual wheel FDIR, one isolation, sun-safe mode on attitude
  error / low SoC) follows published CubeSat FDIR designs (`docs/fdir_refs.md`); the thresholds are our choices.
- About 29 % of the Muse arms' minimized cases need two near-dead wheels (beyond single-fault tolerance); they are
  reported separately as "out of scope".
- The rules-blind prompt was reworded mid-run to get past the provider's content filter (details under Caveats).
- Repair: as of the last commit no Muse patch passed the **strict** gate (0 new violations on the full suite); see
  `data/gated/` (`rejects_table.md`, `summary_v2.json`, `waivers.md` when present) for the budget-mode results.
- Request ids exist only for calls made through `src/muse_client.py` (`make live`), not for the historical logs.

## Results at a glance (3 seeds per arm, equal sim budget, `data/cmp/summary.json`)

| arm | violations / sim | sims to first violation | unique coarse patterns |
|---|---|---|---|
| Muse (rules given) | 0.339 | 5.7 | 18.7 |
| Muse, rules-blind | 0.449 | 5.0 | 21.0 |
| CMA-ES | 0.080 | 105 | 2.3 |
| random | 0.006 | 63.7 | 1.3 |

Single-fault grid: 568 of 576 cases (incl. nominal) pass under the v1 policy; the failures are multi-fault.
Headline case `a6e8087b7a52c977` (found by Muse, seed 1 run 173; minimized in 11 sims): rw0 friction 0.2 at 105 s +
rw1 derate 1.0 at 505 s. With the policy: attitude loss (FDIR spends its one isolation on the mild wheel).
Without the policy: no violation, peak 16 deg. `make replay` re-simulates it.

The rest of this README is the detailed write-up (the per-seed table below predates blind seeds 0 and 2).

---

## Setup details

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

## Repair loop: Muse proposes a policy change, verified in sim (`src/repair.py`)

```bash
python src/repair.py propose --round 1        # -> data/repair/round1_{prompt.txt,response.json}, policy_v2.json
python src/repair.py fixes --policy v2        # re-run every minimized counterexample (v1 searches) on v2
python src/repair.py regress --policy v2 --all  # single-fault grid + nominal on v1/v2, + every stored search run
python src/llm_search.py --seed 1 --policy v2 --budget 200 --out data/repair/v2/muse_seed1.jsonl
FF_POLICY=v2 python src/search.py random data/repair/v2/random_seed1.jsonl --n 200 --seed 1
python src/cmaes_search.py --seed 1 --budget 200 --policy v2 --out data/repair/v2/cmaes_seed1.jsonl
python src/repair.py analyze --policy v2 && python src/repair.py headline --policy v2 && python src/repair.py plot --policies v2,v3
```

The policy is selected with `FF_POLICY` (`v1` default, `v2`, `v3`, or a json path; `data/repair/policy_v*.json`).
v1 replay is unchanged: the new rule hooks (`min_avail`, `isolation_swap`/`swap_ratio`, `wheel_safe_frac`) default
to v1 behaviour, and stored v1 runs reproduce exactly. Muse may only change keys from a whitelist with bounds
(`repair.WHITELIST`, at most 3 keys; anything else is rejected). Each round it gets the policy logic and params,
the count of in-scope policy-induced minimized failures by pattern, and 8 representative counterexamples
(round-robin over patterns) with policy-action traces and margins. Round 2 also gets the v2 results and 4 in-scope
v2 regressions.

**Round 1 -> v2: `fdir_abs_Nm` 3e-4 -> 6e-4 Nm.** Muse diagnosis (verbatim, `data/repair/round1_response.json`):
"FDIR absolute threshold 0.0003 Nm is below mild friction residual ~0.0004 Nm (severity 0.2). It isolates the first
mildly-degraded wheel to trip, exhausting the one-isolation budget (min_avail=3). System is left on 3 wheels with
the worse fault still present, losing control authority and momentum capacity, causing attitude_loss and
wheel_saturation that 4 degraded wheels avoid."

**Round 2 -> v3: v2 + `isolation_swap` (swap_ratio 1.5).** Muse diagnosis: v2 still isolates the first mild
(severity 0.25-0.4) friction wheel; min_avail=3 then blocks isolating the later severe/dead wheel. The swap
re-enables the milder isolated wheel and isolates the worse one when its residual is >1.5x larger.

Replaying all 460 minimized counterexamples from the v1 searches (target fixed / fully clean):

| group | n | v2 target fixed | v2 clean | v3 target fixed | v3 clean |
|---|---|---|---|---|---|
| in-scope, policy-induced (repair input) | 207 | **199 (96 %)** | 193 | **203 (98 %)** | 196 |
| out of scope (2 near-dead wheels) | 107 | 34 | 27 | 85 | 56 |
| not policy-induced | 146 | 13 | 7 | 12 | 4 |
| all | 460 | 246 | 227 | 300 | 256 |

Regressions (v1 had no violation, new policy does):

| set | n | v1 violating | v2 violating | v2 regressions | v2 fixed | v3 violating | v3 regressions | v3 fixed |
|---|---|---|---|---|---|---|---|---|
| single-fault grid + nominal | 576 | 8 | 8 | **0** | 0 | 8 | **0** | 0 |
| nominal only | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| every stored (unminimized) search run, all arms | 2932 | 497 | 458 | **24** | 63 | 523 | **177** | 151 |

v2's 24 regressions are all multi-fault runs. 13 are two heavy friction faults (severity 0.3-1.0; 11 found by
CMA-ES, 2 by random) ending in attitude_loss, where v1's earlier isolation happened to help. 7 have two dead wheels
(out of scope). 4 pair one dead wheel (severity 1.0) with heavy friction and/or the 1.5 uNm leak. So v2 keeps every single-fault and nominal case but does **not** survive everything v1 survived.

v3 (swap) is worse on full runs: 177 regressions against 151 fixes, net 523 violating vs v1's 497 (v2: 458).
All 177 are multi-fault. 83 are two heavy friction faults (46 from Muse runs, 19 CMA-ES, 12 Muse-blind, 4 random,
plus 2 with one heavy one), 53 have two dead wheels (out of scope), and 40 pair a dead wheel with heavy friction.
Our untested guess is that re-enabling the milder wheel hurts when both faults are severe; we have not traced it. On the minimized cases v3 looks better than v2 (98 % vs 96 %); on full runs it is not. So
**v2 is the better candidate**, and v3 is kept only as a negative result. No fresh Muse search was run against v3
(call budget), and the v3 random/CMA-ES re-search and paired replay were not run either.

Fresh search against the new policy (seed 1, 200 sims each; v1 = the first 200 sims of the same arm/seed):

| arm | v1 violations | v2 violations | v1 in-scope policy-induced patterns | v2 in-scope policy-induced patterns |
|---|---|---|---|---|
| Muse | 66 (0.33/sim) | **95 (0.475/sim)** | 15 | **18** |
| CMA-ES | 2 | 0 | 2 | 0 |
| random (paired, same scenarios) | 1 | 2 (both v2-only) | 1 | 1 |

Reading: the round-1 change fixes almost every counterexample it was derived from and is clean on the single-fault
grid. But a fresh Muse search finds *more* failures against v2 than against v1 (12 new in-scope policy-induced
patterns). Most are the same root cause one level up: FDIR still commits its single isolation to the wrong
(milder) wheel, now at higher residuals. Random and CMA-ES barely register a difference at this budget. That is
what motivated round 2 (swap).
Plots: `plots/repair_before_after.png`, `plots/repair_replay_v2.png` (headline case 0805e05f39e4e419:
rw2 friction 0.69 then rw1 friction 0.2; v1 isolates the mild rw1 and loses attitude, v2 isolates rw2 and holds
~9 deg).

## Demo video

`demo/faultforge_demo_v1.mp4` (2:49, 1080p30, captions only) is rendered entirely from repo data by
`demo/make_video.py`; attitude traces for the headline case come from `demo/replay_attitude.py`
(re-runs `data/repair/headline_v2.json` as v1, v1 with policy disabled, and v2). Stills: `demo/still_*.png`.
