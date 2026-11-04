# wheel_saturation rule fix: impact

**Bug.** `src/ff_sim.py` accumulated per-wheel time at >= 98% of max speed over the *whole run* and never reset it, so `wheel_saturation` fired once the *cumulative* time exceeded 60 s. The documented rule (and the analogous attitude_loss rule) is *consecutive*: an available wheel continuously at >= 98% for > 60 s. Short, separated saturation episodes were therefore being counted as violations.

**Fix (2026-11-04).** The counter now resets whenever the wheel drops below the threshold (`CFG['sat_rule']='consecutive'`); the `sat_dur_ratio` near-miss margin is also consecutive. The legacy behaviour is reproducible with `FF_SAT_RULE=cumulative` (verified to reproduce the stored results exactly).

**Method.** Constraint checks are passive (they never feed back into dynamics or the policy), and a cumulative counter is always >= the consecutive one, so the fix can only *remove* `wheel_saturation`. Every stored run that recorded `wheel_saturation` was re-simulated under the fixed rule with its own policy (`python3 src/satfix.py resim`, 1901 unique policy x scenario sims, `data/satfix/resim.jsonl`); no run gained a new violation type and no non-saturation violation changed. Stored datasets were then rewritten in place (`satfix.py apply`), keeping the old result as `violations_legacy_cumulative` / `v1_legacy_cumulative` / `v2_legacy_cumulative`.

**Overall.** 1901 unique (policy, scenario) sims had a legacy wheel_saturation; **768 lose it under the consecutive rule, and 665 of those become fully clean**. For the shipped v1 policy alone: 439 unique scenarios with legacy saturation, 185 lose it, 155 become clean.

## Counts by dataset

`sat` = runs with wheel_saturation (legacy), `sat_only` = wheel_saturation was the only violation, `removed` = runs whose saturation disappears with the fix, violating old -> new.

| dataset | runs | sat | sat_only | removed | violating old | violating new |
|---|---:|---:|---:|---:|---:|---:|
| cmp/cmaes_seed0.jsonl | 300 | 0 | 0 | 0 | 71 | 71 |
| cmp/cmaes_seed1.jsonl | 300 | 1 | 1 | 1 | 12 | 11 |
| cmp/cmaes_seed2.jsonl | 300 | 1 | 1 | 1 | 4 | 3 |
| cmp/muse_seed0.jsonl | 232 | 52 | 40 | 19 | 90 | 75 |
| cmp/muse_seed1.jsonl | 300 | 55 | 40 | 19 | 95 | 80 |
| cmp/muse_seed2.jsonl | 300 | 47 | 38 | 18 | 94 | 78 |
| cmp/museblind_seed0.jsonl | 300 | 86 | 72 | 44 | 139 | 99 |
| cmp/museblind_seed1.jsonl | 300 | 79 | 62 | 45 | 126 | 84 |
| cmp/museblind_seed2.jsonl | 300 | 86 | 65 | 46 | 138 | 98 |
| cmp/random_seed0.jsonl | 300 | 2 | 2 | 0 | 2 | 2 |
| cmp/random_seed1.jsonl | 300 | 0 | 0 | 0 | 2 | 2 |
| cmp/random_seed2.jsonl | 300 | 1 | 1 | 0 | 1 | 1 |
| grid.jsonl | 576 | 8 | 8 | 0 | 8 | 8 |
| random_seed0.jsonl | 300 | 2 | 2 | 0 | 2 | 2 |
| random_seed1.jsonl | 300 | 0 | 0 | 0 | 2 | 2 |
| random_seed2.jsonl | 300 | 1 | 1 | 0 | 1 | 1 |
| gated/heldout_muse_seed100.jsonl | 100 | 32 | 22 | 11 | 48 | 42 |
| gated/fresh/muse_v1_seed300.jsonl | 100 | 13 | 4 | 3 | 39 | 38 |
| repair/regress_v2.jsonl [v1] | 3508 | 246 | 193 | 103 | 505 | 415 |
| repair/regress_v2.jsonl [v2] | 3508 | 255 | 207 | 105 | 466 | 372 |
| repair/regress_v3.jsonl [v1] | 3508 | 246 | 193 | 103 | 505 | 415 |
| repair/regress_v3.jsonl [v2] | 3508 | 210 | 167 | 81 | 531 | 459 |
| gated/eval_b1t1.jsonl | 3508 | 233 | 186 | 115 | 492 | 390 |
| gated/eval_b2t1.jsonl | 797 | 6 | 6 | 2 | 73 | 71 |
| gated/eval_b2t2.jsonl | 659 | 6 | 6 | 2 | 23 | 21 |
| gated/eval_r1t1.jsonl | 861 | 9 | 9 | 0 | 61 | 61 |
| gated/eval_r1t2.jsonl | 1777 | 72 | 61 | 30 | 183 | 157 |
| gated/eval_r1t3.jsonl | 3508 | 209 | 155 | 65 | 471 | 415 |
| gated/eval_r1t4.jsonl | 982 | 18 | 15 | 4 | 97 | 94 |
| gated/eval_r1t5.jsonl | 7 | 0 | 0 | 0 | 3 | 3 |
| gated/eval_r1t6.jsonl | 25 | 0 | 0 | 0 | 3 | 3 |
| gated/eval_r2t1.jsonl | 66 | 1 | 1 | 0 | 4 | 4 |
| gated/eval_r2t2.jsonl | 3508 | 233 | 186 | 115 | 492 | 390 |
| gated/eval_r2t3.jsonl | 3508 | 237 | 189 | 103 | 496 | 406 |
| gated/eval_r2t4.jsonl | 13 | 0 | 0 | 0 | 3 | 3 |
| gated/eval_s1.jsonl | 663 | 8 | 8 | 0 | 25 | 25 |
| gated/eval_s2.jsonl | 794 | 8 | 8 | 0 | 73 | 73 |
| gated/heldout_eval_v1.jsonl | 300 | 33 | 23 | 11 | 51 | 45 |
| gated/fresh/random_v1_k0.jsonl | 200 | 0 | 0 | 0 | 1 | 1 |

Notes: `regress_v3.jsonl [v2]` is policy v3. `gated/eval_*` are gate candidate evaluations on the 3508-run regression suite (many stopped early). `data/random_seed*.jsonl` are the original random baseline files (same scenarios as `cmp/random_*`).

## Headline numbers, old (cumulative) -> new (consecutive)

| number | old | new |
|---|---|---|
| Fresh Muse batch (seed 300, v1 policy) | 39/100 violating | **38/100** |
| Fresh random batch (200, v1 policy) | 1/200 | 1/200 (unchanged) |
| Held-out set (100 Muse + 200 random, v1) | 51/300 (48 + 3) | **45/300** (42 + 3) |
| Single-fault grid + nominal, v1 clean | 568/576 | 568/576 (unchanged: the 8 failures are a constant Z leak saturating a wheel continuously) |
| Regression suite (3508 runs), v1 violating | 505 | **415** |
| Stored v1 search runs (2932), v1 / v2 / v3 violating | 497 / 458 / 523 | **407 / 364 / 451** |
| v2 regressions / fixes on those runs | 24 / 63 | **23 / 66** |
| v3 regressions / fixes on those runs | 177 / 151 | **169 / 125** |
| Headline case a6e8087b7a52c977 | attitude_loss | attitude_loss (unaffected; no saturation involved) |

## Gate decisions re-decided on the corrected suite (stored results re-evaluated, no re-search)

`python3 src/satfix.py gates` -> `data/satfix/gates_corrected.json`; the `*_gate.json` files now hold the corrected
counts in `gate` and the old ones in `gate_legacy_cumulative`. **No accept/reject decision changed.** No early-stopped
evaluation lost its stop condition (each still has >= 3 new violation pairs (strict) or > 3 clean runs broken (budget)),
so no evaluation had to be continued.

| gate | mode / base | old | new | corrected key numbers |
|---|---|---|---|---|
| b1t1 | budget / v1 | accept | **accept (still holds)** | 3508/3508 evaluated, 2 new violation pairs in 2 runs, 1 clean run broken (<= 3), 26 fixes, net +24; 415 -> 390 violating |
| b2t1, b2t2 | budget / b1t1 | reject | reject | 4 clean runs broken (> 3) |
| r1t1-r1t6, r2t1-r2t4, s1, s2 | strict / v1 | reject | reject | all still >= 1 new violation (r2t2 = same change as b1t1: 2 new pairs; r2t3: 2) |

Note: the Muse/CMA-ES searches themselves ran with the legacy rule (Muse saw legacy margins, CMA-ES optimized a margin
using the legacy `sat_dur_ratio`). Their stored scenarios were re-scored, not re-searched; a search under the
corrected rule could explore somewhat differently.

## Arms comparison, old (cumulative) -> new (consecutive)

`src/compare.py` re-run on the re-scored arm files (stale minimized cache entries re-minimized; new entries stamped
with `sat_rule`). Equal budget per seed (truncated to the shortest arm, 232 sims on seed 0). Source:
`data/cmp/summary.json` (new), `data/satfix/cmp_summary_legacy_cumulative.json` (old); plot `plots/arms_comparison.png`
(old plot: `data/satfix/arms_comparison_legacy_cumulative.png`).

| arm | viol/sim old -> new | sims to 1st old -> new | fine old -> new | coarse old -> new | pol-ind fine old -> new | in-scope old -> new | oos share old -> new |
|---|---|---|---|---|---|---|---|
| Muse (mean, 3 seeds) | 0.339 -> 0.283 | 5.7 -> 7.7 | 39.0 -> 32.0 | 18.7 -> 15.7 | 28.3 -> 21.0 | 18.3 -> 15.0 | 0.29 -> 0.26 |
| Muse-blind (mean, 3 seeds) | 0.449 -> 0.316 | 5.0 -> 6.0 | 43.3 -> 33.7 | 21.0 -> 16.3 | 34.7 -> 24.7 | 22.7 -> 17.3 | 0.28 -> 0.24 |
| CMA-ES (mean, 3 seeds) | 0.080 -> 0.077 | 105.0 -> 119.3 | 3.3 -> 2.7 | 2.3 -> 1.7 | 3.3 -> 2.7 | 3.3 -> 2.7 | 0.00 -> 0.00 |
| random (mean, 3 seeds) | 0.006 -> 0.006 | 63.7 -> 63.7 | 1.7 -> 1.7 | 1.3 -> 1.3 | 0.7 -> 0.7 | 0.7 -> 0.7 | 0.00 -> 0.00 |

| seed | arm | sims | violations old -> new | viol/sim old -> new | sims to 1st old -> new | fine old -> new | coarse old -> new | in-scope pol-ind old -> new |
|---|---|---|---|---|---|---|---|---|
| 0 | Muse | 232 | 90 -> 75 | 0.388 -> 0.323 | 4 -> 4 | 40 -> 31 | 19 -> 15 | 19 -> 15 |
| 0 | Muse-blind | 232 | 108 -> 79 | 0.466 -> 0.341 | 5 -> 5 | 40 -> 32 | 23 -> 16 | 22 -> 15 |
| 0 | CMA-ES | 232 | 43 -> 43 | 0.185 -> 0.185 | 4 -> 4 | 4 -> 4 | 2 -> 2 | 4 -> 4 |
| 0 | random | 232 | 2 -> 2 | 0.009 -> 0.009 | 10 -> 10 | 2 -> 2 | 1 -> 1 | 0 -> 0 |
| 1 | Muse | 300 | 95 -> 80 | 0.317 -> 0.267 | 3 -> 9 | 43 -> 37 | 20 -> 18 | 19 -> 16 |
| 1 | Muse-blind | 300 | 126 -> 84 | 0.420 -> 0.280 | 6 -> 9 | 35 -> 28 | 19 -> 15 | 15 -> 12 |
| 1 | CMA-ES | 300 | 12 -> 11 | 0.040 -> 0.037 | 154 -> 197 | 4 -> 3 | 3 -> 2 | 4 -> 3 |
| 1 | random | 300 | 2 -> 2 | 0.007 -> 0.007 | 15 -> 15 | 2 -> 2 | 2 -> 2 | 2 -> 2 |
| 2 | Muse | 300 | 94 -> 78 | 0.313 -> 0.260 | 10 -> 10 | 34 -> 28 | 17 -> 14 | 17 -> 14 |
| 2 | Muse-blind | 300 | 138 -> 98 | 0.460 -> 0.327 | 4 -> 4 | 55 -> 41 | 21 -> 18 | 31 -> 25 |
| 2 | CMA-ES | 300 | 4 -> 3 | 0.013 -> 0.010 | 157 -> 157 | 2 -> 1 | 2 -> 1 | 2 -> 1 |
| 2 | random | 300 | 1 -> 1 | 0.003 -> 0.003 | 166 -> 166 | 1 -> 1 | 1 -> 1 | 0 -> 0 |

Union of fine patterns over seeds (policy-induced in brackets), old -> new: Muse 71 (53) -> 61 (41), Muse-blind 90 (73) -> 69 (52), CMA-ES 7 (7) -> 5 (5), random 5 (2) -> 5 (2).
Fine patterns found by only one arm, old -> new: Muse 31 -> 25, Muse-blind 49 -> 32, CMA-ES 2 -> 0, random 3 -> 3.

Part of the Muse and Muse-blind saturation hits were produced by the cumulative bug (saturation episodes summed
across the run instead of one > 60 s episode): Muse loses 15-16 violating runs per seed, Muse-blind 29-42, CMA-ES 0-1,
random 0. The ordering is unchanged: both Muse arms still lead CMA-ES/random by a wide margin on rate and diversity.
Muse-blind vs Muse after the fix: higher violations/sim on all 3 seeds (0.341 vs 0.323, 0.280 vs 0.267,
0.327 vs 0.260); more coarse patterns on seeds 0 and 2 (16 vs 15, 18 vs 14) but not seed 1 (15 vs 18; also not
before the fix, 19 vs 20).

