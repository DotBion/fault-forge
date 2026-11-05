# FaultForge

**Quickstart** (Linux x86_64, Python 3.13; no API key needed for the first two lines):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # or: make setup
make replay                                    # keyless: re-sim headline case policy on/off + recorded Muse calls
cp .env.example .env   # put your key in .env, then:  make live   (one live Muse Spark search round)
```

FaultForge hands an FDIR team the multi-fault combinations a test campaign would miss, each as a one-command
replay. Meta's Muse Spark model searches a Basilisk CubeSat simulation for fault combinations that make a
rule-based recovery (safe-mode / FDIR) policy violate its safety constraints; every violation is minimized to a
small counterexample, re-run with the policy disabled, and replayable with one command. Muse then writes a diagnosis
and selects and parameterizes a repair from an engineer-provided menu of repair options (whitelisted policy keys
with bounds). A regression gate that Muse does not control re-simulates the full suite and accepts or rejects it.
The **strict** gate (0 new violations) rejected every proposal; the **budget** gate (net fixes > 0, <= 3 previously
clean runs broken) accepted one, b1t1 (see [Repair: gates](#repair-gates-strict-vs-budget)).

Before this hackathon week the project had the Basilisk harness and the rule-based FDIR policy. This week we implemented:
the Muse-guided search, the rules-blind variant, CMA-ES and random baselines, the minimizer/compare pipeline,
the Muse repair loop and the regression gate.

## Meta models used

One model, **`muse-spark-1.3`**, via the Meta Model API: `POST https://api.meta.ai/v1/chat/completions`
(OpenAI-compatible, JSON mode, key in `MUSE_API_KEY`). It is used in four roles:

| role | what Muse does | code | recorded calls |
|---|---|---|---|
| scenario search | each round reads the fault schema, the policy description, the failures found so far and near-miss margins, and returns 8 new fault scenarios as JSON | `src/llm_search.py`, `src/live_round.py` | `data/cmp/muse_seed*_calls.jsonl` |
| blind rule inference | same search with the policy thresholds and the one-isolation rule hidden; it must infer the rules from outcomes (by round 4 of seed 1 it wrote "FDIR isolates at most one wheel") | `src/llm_search.py --blind` | `data/cmp/museblind_seed*_calls.jsonl` |
| diagnosis | reads minimized counterexamples with policy traces and writes a free-text explanation of why the policy failed (not checked by the gate) | `src/gated_repair.py`, `src/gated_v2.py` (also `src/repair.py`) | `data/gated/*_response.json` (`diagnosis`) |
| repair selection | selects and parameterizes a repair from an engineer-provided menu (whitelisted policy keys with bounds, at most 3 keys); the gate re-simulates it on the full suite, and rejections (with regressions + traces) go back to Muse | same | `data/gated/*_response.json` (`change`), `*_gate.json` |

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
- About 25 % of the Muse arms' minimized cases need two near-dead wheels (beyond single-fault tolerance); they are
  reported separately as "out of scope".
- The rules-blind prompt was reworded mid-run to get past the provider's content filter (details under Caveats).
- **Repair is menu-based.** Muse selects and parameterizes from an engineer-provided menu of repair options; it does
  not write policy code. No proposal passed the **strict** gate. One (b1t1) passed the **budget** gate, which by
  design accepts a patch that breaks up to 3 previously clean runs (b1t1 breaks 1). See
  [Repair: gates](#repair-gates-strict-vs-budget).
- **The single-fault grid is not independent validation.** 568/576 means the policy passes its own single-fault
  acceptance test (its thresholds were tuned to it).
- **Blind vs informed Muse is a hypothesis.** Rules-blind Muse is higher on violations/sim on all 3 seeds but higher on
  distinct fault-combination signatures on only 2 of 3; 3 seeds do not settle the ordering.
- **Most of the gap over plain random is Muse's choice of where to look, and a sampler can copy it in hindsight.**
  Plain random is i.i.d. over the whole space. Random restricted to Muse's fault families gets only 0.031
  violations/sim, but random that also samples each parameter from Muse's own proposals gets 0.307, level with Muse
  (0.283) and with more coarse signatures (17.7 vs 15.7). That baseline exists only because Muse was run first; see
  [Matched-random baselines](#matched-random-baselines-is-muse-just-picking-the-right-fault-family).
- **The policy has an implementation bug** (FDIR same-step tie-break by wheel index, see Defect 4). We report it and
  did not fix it, so every number here is for the policy as written.
- Request ids exist only for calls made through `src/muse_client.py` (`make live`), not for the historical logs.

## Results at a glance (3 seeds per arm, equal sim budget, `data/cmp/summary.json`)

| arm | violations / sim | sims to first violation | distinct fault-combination signatures (coarse) |
|---|---|---|---|
| Muse (rules given) | 0.283 | 7.7 | 15.7 |
| Muse, rules-blind | 0.316 | 6.0 | 16.3 |
| CMA-ES | 0.077 | 119 | 1.7 |
| random | 0.006 | 63.7 | 1.3 |

Muse finds about 46x more violations per sim than random (0.283 vs 0.006; ratio of the unrounded means 45.6) and about 9x more distinct
fault-combination signatures than CMA-ES (15.7 vs 1.7). A signature is the set of fault kinds in a minimized case;
it is a count of distinct combinations, not of distinct defects (the defects are below). Numbers above and below use
the corrected (consecutive) wheel-saturation rule; see the Changelog.

Single-fault grid: the policy passes its own single-fault acceptance test (its thresholds were tuned to it): 568 of
576 cases (incl. nominal), unchanged by the saturation fix. This is a sanity check, not independent validation. The 8
failures are all one single fault: a 1.5 uNm external torque leak on +Z from t = 0 (at beta 5/35/65 deg), which
saturates a wheel for > 60 s consecutive because the sim has no momentum dumping.

Headline **minimized case** `a6e8087b7a52c977` (minimized in 11 sims from Muse seed 1 run 173): rw0 friction 0.2 at
105 s + rw1 derate 1.0 at 505 s. Note that the *original* run 173 (more faults) also fails with the policy off
(attitude_loss @3015 s); the minimized case is the one where the policy alone causes the failure. `make causal` re-runs
it with *only* wheel isolation suppressed (everything else in the policy unchanged). On the safety rule (attitude
error > 30 deg for more than 1200 s), the longest stretch over 30 deg is **9,645 s with the full policy vs 30 s with
isolation suppressed** (0 s with the policy off). In a 24-case neighbourhood sweep the full policy violates in 24/24
and isolation-suppressed in 0/24. The peak error is 179.9 deg vs 136.9 deg: suppressing isolation does not keep the
craft pointed (it tumbles through safe mode), but it recovers within the limit. Details: `data/satfix/causal_replay.md`.
`make replay` re-simulates the case with the policy on/off.

## Defects found

`make defects` (`src/defects.py`) re-runs all 276 in-scope, policy-induced minimized cases under single-change
ablations (`full`, `no_isolate`, `swap`, `no_safe`, `off`) and assigns each to the change that removes the failure.
Full write-up: `data/satfix/defects.md`; raw: `data/satfix/defects.json`. Replay any case:
`python3 src/defects.py --replay KEYPREFIX ARM`.

| # | defect | cases | removing the cause fixes it | example key | replay |
|---|---|---|---|---|---|
| D1 | isolation lock-in: the one allowed isolation is spent on the milder fault | 254 / 276 | no_isolate 254/254, swap 253/254 | `a6e8087b` | `python3 src/defects.py --replay a6e8087b full` (then `no_isolate`, `swap`) |
| D2 | isolation removes a wheel that is still needed (13 under a torque leak, 6 a healthy wheel) | 19 / 276 | no_isolate 19/19 | `b8aa55fd` | `python3 src/defects.py --replay b8aa55fd full` (then `no_isolate`) |
| D3 | safe-mode chattering: no attitude hysteresis, SAFE/NOMINAL re-slews pump a wheel into saturation | 3 / 276 | no_safe 3/3 | `8a5158f3` | `python3 src/defects.py --replay 8a5158f3 full` (then `no_safe`) |
| D4 | implementation bug in the policy: same-step threshold crossings resolved by wheel index, not residual | 63 / 276 (59 inside D1, 4 inside D2) | (not fixed; reported) | `059def4e` | `python3 src/defects.py --tiebreak 059def4e` |

**D1 causal trace** (`a6e8087b`): t=105 s rw0 friction 0.2 -> t=120 s FDIR isolates rw0 (residual 3.99e-4 Nm, just
over the 3e-4 threshold), using its only isolation (`min_avail=3`) -> t=505 s rw1 dies (derate 1.0); FDIR detects it
but may not isolate it, so the controller keeps commanding a dead wheel -> SAFE at 930 s, never recovers ->
attitude_loss @2915 s. With `no_isolate`: no violation. With `swap` (isolate the worse wheel instead): no violation.

**D2 causal trace** (`b8aa55fd`, healthy-wheel variant): heater 5.2 W @3000 s, rw1 dead @3500 s -> SAFE on low SoC ->
back to NOMINAL at 5285 s; during the re-slew at t=5300 s FDIR isolates **rw0, which has no fault** (residual 1.09e-3
Nm), while dead rw1 crossed in the same step with 2.20e-3 Nm -> attitude_loss @6805 s. With `no_isolate`: no violation.

**D3 causal trace** (`8a5158f3`): rw1 dead + rw3 friction 0.35 + 1.0 uNm leak @100 s -> FDIR correctly isolates rw1 ->
on 3 wheels with a leak the attitude error hovers at 15-19 deg, so SAFE (> 15 deg for 120 s) and NOMINAL (SoC > 70 %
after 600 s) alternate 13 times; each re-slew adds momentum -> wheel_saturation @10660 s. With `no_safe`: no
violation, peak 17.1 deg.

**D4: FaultForge surfaced an implementation bug in the policy itself.** The FDIR loop in `src/ff_sim.py` walks the
wheels in index order and isolates the first one whose residual count reaches the persistence threshold. When two
wheels cross in the same 5 s step it never compares residuals. This happened in 63 of 276 cases, and in all 63 the
wheel with the *smaller* residual was isolated. Example `059def4e` (rw0 friction 0.2 and rw1 friction 0.725, both at
t=0): at t=15 s both cross, rw0 at 4.76e-4 Nm and rw1 at 8.41e-4 Nm; FDIR isolates rw0 (lower index), then cannot
isolate rw1 -> attitude_loss @3765 s. `python3 src/defects.py --tiebreak 059def4e` replays it and prints both
residuals; `python3 src/defects.py --tiebreak` lists all 63 from `defects.json`. We did not fix this bug: every result
in this README is for the policy as written, bug included.

## Changelog

### 2026-11-04: wheel_saturation rule fixed (cumulative -> consecutive)

**Bug.** The documented constraint is "no available wheel at >= 98 % max speed for > 60 s *consecutive*", but
`src/ff_sim.py` summed each wheel's time above 98 % over the whole run and never reset it. Several short, separate
saturation episodes adding up to > 60 s were therefore scored as a `wheel_saturation` violation.

**Fix.** The counter now resets whenever the wheel drops below 98 % (`CFG["sat_rule"] = "consecutive"`); the
`sat_dur_ratio` near-miss margin is consecutive too. The old behaviour is still available with
`FF_SAT_RULE=cumulative`, and it reproduces the stored results exactly.

**Impact.** The checks are passive and a cumulative counter is always >= a consecutive one, so the fix can only
remove saturation violations. Every stored run with a legacy saturation hit was re-simulated (`src/satfix.py`,
1901 unique policy x scenario sims). 768 lose the violation and 665 of those become fully clean. No run gained a
violation type and no other violation changed. **Part of the Muse and Muse-blind saturation hits came from this bug**:
Muse loses 15-16 violating runs per seed and Muse-blind 29-42. CMA-ES loses 0-1 and random 0, because their hits are
mostly attitude loss. The arm ordering does not change. Details: `data/satfix/impact.md`.

| per seed (equal budget) | Muse viol. runs | Muse-blind viol. runs | CMA-ES viol. runs | random viol. runs |
|---|---|---|---|---|
| seed 0 (232 sims) | 90 -> 75 | 108 -> 79 | 43 -> 43 | 2 -> 2 |
| seed 1 (300 sims) | 95 -> 80 | 126 -> 84 | 12 -> 11 | 2 -> 2 |
| seed 2 (300 sims) | 94 -> 78 | 138 -> 98 | 4 -> 3 | 1 -> 1 |

| arm (mean of 3 seeds) | violations / sim | sims to 1st | fine signatures | coarse signatures |
|---|---|---|---|---|
| Muse | 0.339 -> 0.283 | 5.7 -> 7.7 | 39.0 -> 32.0 | 18.7 -> 15.7 |
| Muse-blind | 0.449 -> 0.316 | 5.0 -> 6.0 | 43.3 -> 33.7 | 21.0 -> 16.3 |
| CMA-ES | 0.080 -> 0.077 | 105 -> 119 | 3.3 -> 2.7 | 2.3 -> 1.7 |
| random | 0.006 -> 0.006 | 63.7 -> 63.7 | 1.7 -> 1.7 | 1.3 -> 1.3 |

| other numbers | old (cumulative) | new (consecutive) |
|---|---|---|
| Fresh Muse batch (seed 300, v1) | 39/100 violating | 38/100 |
| Fresh random batch (v1) | 1/200 | 1/200 |
| Held-out set (100 Muse + 200 random, v1) | 51/300 | 45/300 |
| Regression suite (3508 runs), v1 violating | 505 | 415 |
| Single-fault grid + nominal, v1 clean | 568/576 | 568/576 |
| Gate b1t1 (budget mode, `wheel_safe_frac` 0.97 / `wheel_safe_s` 60) | accept: 13 fixes, 0 clean runs broken, net +12 | **accept: 26 fixes, 2 runs with new violations (1 previously clean, waived; <= 3), net 26 - 2 = +24** |

**Gates.** All gates were re-decided on the corrected suite (`python3 src/satfix.py gates`). No accept/reject
decision changed: b1t1 still passes the budget gate; b2t1/b2t2 are still rejected (4 clean runs broken); every
strict-gate try is still rejected (each still has >= 1 new violation). No early-stopped evaluation lost its stop
condition. The `*_gate.json` files keep the old counts under `gate_legacy_cumulative`.

**Caveat.** The searches ran under the legacy rule: Muse saw the legacy margins, and CMA-ES optimized a margin that
used the legacy `sat_dur_ratio`. Their stored scenarios were re-scored, not re-searched. Two tables in the repair
section are still on the legacy rule and are marked that way.

The rest of this README is the detailed write-up.

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
src/compare.py     equal-budget Muse vs random: minimize every violation, dedupe signatures, summary + plot
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
  no available wheel at >= 98% max speed for > 60 s consecutive (one continuous episode; until 2026-11-04 the
  code summed all saturated time over the run, see the Changelog).

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
the minimized target violation does not occur without the policy. Distinct fault-combination signatures: fine =
violation <- faults with wheel index / dominant leak axis; coarse = fault kinds only. Signatures are combinations, not
defects. *Out of scope* = the minimized case still needs >= 2
torque-derated wheels with severity >= 0.9 (two near-dead wheels, beyond a single-fault-tolerant 4-wheel design).

| seed | arm | sims | violations/sim | sims to 1st | fine signatures | coarse signatures | policy-induced fine | ... in scope | out-of-scope share |
|---|---|---|---|---|---|---|---|---|---|
| 0 | Muse | 232* | 0.323 (75) | 4 | 31 | 15 | 19 | 15 | 0.24 |
| 0 | Muse-blind | 232* | 0.341 (79) | 5 | 32 | 16 | 20 | 15 | 0.19 |
| 0 | CMA-ES | 232* | 0.185 (43) | 4 | 4 | 2 | 4 | 4 | 0.00 |
| 0 | random | 232* | 0.009 (2) | 10 | 2 | 1 | 0 | 0 | 0.00 |
| 1 | Muse | 300 | 0.267 (80) | 9 | 37 | 18 | 25 | 16 | 0.30 |
| 1 | Muse-blind | 300 | 0.280 (84) | 9 | 28 | 15 | 20 | 12 | 0.27 |
| 1 | CMA-ES | 300 | 0.037 (11) | 197 | 3 | 2 | 3 | 3 | 0.00 |
| 1 | random | 300 | 0.007 (2) | 15 | 2 | 2 | 2 | 2 | 0.00 |
| 2 | Muse | 300 | 0.260 (78) | 10 | 28 | 14 | 19 | 14 | 0.24 |
| 2 | Muse-blind | 300 | 0.327 (98) | 4 | 41 | 18 | 34 | 25 | 0.26 |
| 2 | CMA-ES | 300 | 0.010 (3) | 157 | 1 | 1 | 1 | 1 | 0.00 |
| 2 | random | 300 | 0.003 (1) | 166 | 1 | 1 | 0 | 0 | 0.00 |
| mean | Muse (3 seeds) | | 0.283 | 7.7 | 32.0 | 15.7 | 21.0 | 15.0 | 0.26 |
| mean | Muse-blind (3 seeds) | | 0.316 | 6.0 | 33.7 | 16.3 | 24.7 | 17.3 | 0.24 |
| mean | CMA-ES (3 seeds) | | 0.077 | 119.3 | 2.7 | 1.7 | 2.7 | 2.7 | 0.00 |
| mean | random (3 seeds) | | 0.006 | 63.7 | 1.7 | 1.3 | 0.7 | 0.7 | 0.00 |

\* Seed 0 Muse was stopped at 232 sims (API call cap). Every arm is truncated to the shortest arm per seed, so the
budget is equal; over their full 300 sims seed 0 CMA-ES had 71 violations, Muse-blind 99.

Union of fine signatures over seeds: Muse 61 (41 policy-induced), Muse-blind 69 (52), CMA-ES 5 (5), random 5 (2).
Fine signatures found by only one arm: Muse 25, Muse-blind 32, CMA-ES 0, random 3. Plot: `plots/arms_comparison.png`.

Reading the table:
- Both Muse arms beat CMA-ES and random by a wide margin on *diversity*: 12-25 in-scope policy-induced fine
  signatures per seed vs 1-4 for CMA-ES. CMA-ES can match Muse on raw violation rate when it converges early (seed 0),
  but it then refines one fault combination; on seeds 1-2 it took 157-197 sims to find any violation. Its rate varies a lot
  by seed (71 / 11 / 3 per 300).
- **Rules-blind vs white-box Muse (hypothesis, not a finding).** Blind has a higher violation rate on all 3 seeds
  (0.341 / 0.280 / 0.327 vs 0.323 / 0.267 / 0.260) but more coarse signatures on only 2 of 3 (16 vs 15, 18 vs 14;
  fewer on seed 1, 15 vs 18; fine 28 vs 37, in-scope policy-induced 12 vs 16). Our hypothesis is that hiding the rules
  does not hurt this search; 3 seeds with small gaps cannot confirm it. On seed 1 all 84 of its
  violations came from its 252 model-proposed sims (the 48 fallback sims had none). From isolated_wheels and
  outcomes alone it inferred by round 4 that FDIR only ever isolates one wheel. The gaps on seeds 0-1 are small,
  so treat the blind-vs-white-box ordering as indicative only.
- About 19-30 % of the Muse arms' minimized cases are out of scope (two near-dead wheels). CMA-ES and random found
  none, so their few finds are all "in scope", but there are few of them.

LLM cost: white-box Muse 105 rounds, ~1.55M tokens, mean latency ~31 s/call. Blind seed 1: 39 rounds, ~0.44M tokens,
~27 s/call.

Caveats
- Fine signatures over-count (wheel-index permutations of one combination); coarse signatures are the conservative
  number. Neither counts defects: 276 cases with many signatures reduce to the 3 defect classes above.
  ~54 Muse runs (legacy-rule count) repeat one known single-fault weakness (a ~1.1 uNm Z leak saturating wheel 2 with no momentum dumping).
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

## Matched-random baselines: is Muse just picking the right fault family?

Equal budget, 3 seeds, corrected saturation rule. Full table, arm definitions and Muse call provenance:
`data/matched/report.md` (`data/matched/summary.json`; plot `plots/arms_comparison_matched.png`).

| arm | violations / sim | coarse signatures | sims to first violation |
|---|---|---|---|
| Muse-guided (closed loop) | 0.283 | 15.7 | 7.7 |
| Muse rules-blind (closed loop) | 0.316 | 16.3 | 6.0 |
| One-shot Muse bank (40) + random mutations | 0.142 | 6.7 | 10.0 |
| Matched random: family + Muse's parameter marginals | 0.307 | 17.7 | 2.0 |
| Matched random: family only | 0.031 | 4.0 | 30.0 |
| CMA-ES | 0.077 | 1.7 | 119.3 |
| plain random | 0.006 | 1.3 | 63.7 |

Reading it straight:
- Fault families alone explain little: random over Muse's fault-kind mix gets 0.031, about 5x plain random but
  about 9x below Muse.
- The parameter values carry the effect. Muse converged to severe, early wheel faults (76% of derates and 85% of
  friction faults at severity 1.0, median onset 0.9% into the run, median beta 5 deg). Random that samples from those marginals matches
  Muse (0.307 vs 0.283) and slightly exceeds it on signatures. So once you know Muse's distribution, an open-loop
  sampler is as good; the closed-loop search is not adding much beyond finding that distribution.
- That baseline is hindsight-informed: its marginals come from Muse's feedback-driven runs. Without feedback, a
  single 40-scenario Muse call plus random mutations gets 0.142, about half of closed-loop Muse, which suggests
  the feedback loop is how Muse found the region.
- 3 seeds per arm; treat the Muse vs matched fam+param ordering as a tie.

## Repair: gates (strict vs budget)

Muse selects and parameterizes from an engineer-provided menu of repair options: whitelisted policy keys with bounds
(17 keys in `repair.WHITELIST`, e.g. FDIR thresholds, isolation swap, safe-mode triggers, a wheel-speed SAFE guard), at most 3 keys per proposal. It does not
write policy code. Each proposal is re-simulated by `src/gated_repair.py` / `src/gated_v2.py` on the full 3,508-run
suite (576-case grid + 2,932 stored search runs). Two gates, reported separately:

- **Strict gate** (0 new (run, violation) pairs and > 0 fixes): **rejected every proposal** (r1t1-r1t6, r2t1-r2t4,
  structural s1-s2; 12 proposals). Table: `data/gated/rejects_table.md`.
- **Budget gate** (net fixes > 0 and <= 3 previously clean runs broken per accepted patch): accepted one patch,
  **b1t1** = `wheel_safe_frac 0.97, wheel_safe_s 60` (enter SAFE if an in-use wheel stays >= 97 % speed for 60 s):
  **26 fixes, 2 runs with new violations, net +24; 1 previously clean run broken: `museblind_seed1_28`** (leak + rw2/rw3
  dead, now wheel_saturation @9290 s; waiver and replay commands in `data/gated/waivers.md`). Round 2 (b2t1, b2t2)
  was rejected (4 clean runs broken each) and the budget loop was stopped there.
- **Cumulative effect of the budget across rounds:** only round 1 was accepted, so the accepted chain is v1 -> b1t1
  with 1 waived clean run in total (budget 3 per patch). Suite violating runs: 415 (v1) -> 390 (b1t1).

**Does b1t1 cut fresh violations?** Modestly, yes (`python3 src/gated_v2.py fresh` then `report`;
`data/gated/fresh/result_{v1,b1t1}.json`, `data/gated/summary_v2.json`, chart `plots/gated_repair_trend.png`):

| fresh check (consecutive sat rule) | v1 | b1t1 |
|---|---|---|
| new Muse search against the policy (100 sims; seed 300 for v1, 301 for b1t1) | 38/100 | 31/100 |
| uniform random (200 sims; k0 for v1, k1 for b1t1) | 1/200 | 0/200 |
| fixed held-out set (same 300 scenarios for both, paired) | 45/300 | 41/300 (4 fixed, 0 new) |

The Muse and random rows are **unpaired** (each policy gets its own new search seed, as the gate design intends), and
100-200 sims are small samples, so the 38 -> 31 drop is suggestive, not significant on its own. The paired held-out
row is the cleaner evidence: 4 violating runs fixed and none broken. `summary_v2.json` records
`trend_down_fresh_muse: true`.

## Repair loop (legacy, `src/repair.py`): Muse proposes a policy change, verified in sim

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

Replaying all 460 minimized counterexamples from the v1 searches (target fixed / fully clean; **legacy cumulative
saturation rule**, not recomputed after the 2026-11-04 fix):

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
| every stored (unminimized) search run, all arms | 2932 | 407 | 364 | **23** | 66 | 451 | **169** | 125 |
| ... same, legacy cumulative rule (before the fix) | 2932 | 497 | 458 | 24 | 63 | 523 | 177 | 151 |

v2's 23 regressions (24 under the legacy rule; the breakdown below is for those 24) are all multi-fault runs. 13 are two heavy friction faults (severity 0.3-1.0; 11 found by
CMA-ES, 2 by random) ending in attitude_loss, where v1's earlier isolation happened to help. 7 have two dead wheels
(out of scope). 4 pair one dead wheel (severity 1.0) with heavy friction and/or the 1.5 uNm leak. So v2 keeps every single-fault and nominal case but does **not** survive everything v1 survived.

v3 (swap) is worse on full runs: 169 regressions against 125 fixes, net 451 violating vs v1's 407 (v2: 364; legacy
rule: 177 / 151, 523 vs 497, v2 458). All are multi-fault; legacy breakdown of the 177: 83 are two heavy friction faults (46 from Muse runs, 19 CMA-ES, 12 Muse-blind, 4 random,
plus 2 with one heavy one), 53 have two dead wheels (out of scope), and 40 pair a dead wheel with heavy friction.
Our untested guess is that re-enabling the milder wheel hurts when both faults are severe; we have not traced it. On the minimized cases v3 looks better than v2 (98 % vs 96 %); on full runs it is not. So
**v2 is the better candidate**, and v3 is kept only as a negative result. No fresh Muse search was run against v3
(call budget), and the v3 random/CMA-ES re-search and paired replay were not run either.

Fresh search against the new policy (seed 1, 200 sims each; v1 = the first 200 sims of the same arm/seed;
**legacy cumulative saturation rule**, not re-scored):

| arm | v1 violations | v2 violations | v1 in-scope policy-induced signatures | v2 in-scope policy-induced signatures |
|---|---|---|---|---|
| Muse | 66 (0.33/sim) | **95 (0.475/sim)** | 15 | **18** |
| CMA-ES | 2 | 0 | 2 | 0 |
| random (paired, same scenarios) | 1 | 2 (both v2-only) | 1 | 1 |

Reading: the round-1 change fixes almost every counterexample it was derived from and is clean on the single-fault
grid. But a fresh Muse search finds *more* failures against v2 than against v1 (12 new in-scope policy-induced
signatures). Most are the same root cause one level up: FDIR still commits its single isolation to the wrong
(milder) wheel, now at higher residuals. Random and CMA-ES barely register a difference at this budget. That is
what motivated round 2 (swap).
Plots: `plots/repair_before_after.png`, `plots/repair_replay_v2.png` (headline case 0805e05f39e4e419:
rw2 friction 0.69 then rw1 friction 0.2; v1 isolates the mild rw1 and loses attitude, v2 isolates rw2 and holds
~9 deg).

## Related work

- **LLM-Falsifier.** A. ArjomandBigdeli, J. Zhou, S. Bak, "Large Language Models as Falsifiers for Cyber-Physical
  Systems", arXiv:2609.20752 (Sep 2026). An LLM proposes falsifying inputs that minimize STL robustness, using
  semantic information (signal names, trajectories, critical-time witnesses), on top of Psi-TaLiRo; it beat ARCH-COMP
  tools on 14 of 21 specs by simulations to a counterexample. FaultForge applies the same idea to a different
  object (discrete multi-fault combinations against an FDIR/safe-mode policy in Basilisk) and adds minimization,
  policy-off attribution, ablation-based defect classes and a gated, menu-based repair step. We implemented this
  combination; we do not claim it is the first.
- Simulation-based falsification tools (S-TaLiRo / Psi-TaLiRo, Breach, ARCH-COMP falsification track) and CMA-ES as a
  black-box optimizer baseline. FDIR design references: `docs/fdir_refs.md`.

## Demo video

**Current: `demo/faultforge_demo_v4.mp4`** (177.7 s, 2:57, 1080p30, narrated). Re-render with `bash demo/render_v4.sh`
(edge-tts narration from `demo/v4_script.py` -> `demo/vo_v4/`, segments via `demo/make_video_v4.py`; timed script and
on-screen data sources in `docs/video_v4_script.md`). Every number is read from the repo at render time. Order, one
takeaway per scene:
(0) the problem in plain words, narrated in three beats over a title card ("When a satellite has a problem, its software
automatically tries to keep it safe. But a response that helps with one failure can make a second failure worse—and the
satellite can lose control." / "Testing failures one at a time can miss these dangerous interactions." / "FaultForge uses
AI to find them in simulation, so engineers can investigate them before launch."); (1) the minimized case `a6e8087b`, full policy vs the same policy with only isolation
suppressed (Basilisk replay, `demo/replay_causal_v4.py`), ending on the safety-rule metric (longest stretch > 30 deg:
9,645 s vs 30 s; 24/24 vs 0/24 nearby variants) before the peak-angle context; (2) Muse's four labelled roles, then the
real, unedited `make live` take (`demo/live/take1.cast`; only the Muse wait is sped up and labelled), ending on
"Muse proposed 8 tests -> sim found 2 failures" with the live call's model, endpoint, response id, x-request-id and
token counts in a footer (recorded calls have no request id); (3) defect classes D1-D3 and the D4 tie-break bug, with
counts and replay commands; (4) chart 1, four bars of violations/sim: plain random 0.006, one Muse call + random
mutations 0.142, Muse closed loop 0.283, and marginals-matched random 0.307 (samples Muse's learned distribution, so it
needs finished Muse runs); CMA-ES 0.077, family-only random 0.031 and rules-blind Muse 0.316 in the footnote (see
[Matched-random baselines](#matched-random-baselines-is-muse-just-picking-the-right-fault-family)); (5) repair: held-out
4 fixed / 0 newly broken (same 300 scenarios, paired), the strict gate (rejects all) and the budget gate (b1t1: 26 suite
runs fixed, 2 runs with a new violation of which 1 was previously clean -> net 26 - 2 = +24; the clean one,
`museblind_seed1_28`, is waived). The unpaired fresh-search check (38 -> 31 of 100) is above, not in the video;
(6) three limits plus a pointer to [Limitations](#limitations-and-honest-scope), related work, and `make replay`. Stills: `demo/v4_still_*.png`.

Previous: `demo/faultforge_demo_v3.mp4` (2:53), `bash demo/render_v3.sh`, script `docs/video_v3_script.md`.

Older version:
`demo/faultforge_demo_v1.mp4` (2:49, 1080p30, captions only) is rendered entirely from repo data by
`demo/make_video.py`; attitude traces for the headline case come from `demo/replay_attitude.py`
(re-runs `data/repair/headline_v2.json` as v1, v1 with policy disabled, and v2). Stills: `demo/still_*.png`.
