# Is Muse just picking the right fault family? Matched-random baselines

All arms scored with the **corrected wheel_saturation rule** (consecutive > 60 s; fix c09fbf5, impact in `data/satfix/impact.md`). Equal sim budget per seed (seed 0: 232, seed 1: 300, seed 2: 300), 3 seeds per arm, same simulator, policy v1, same minimization + pattern code (`src/compare.py` functions).
Cells: **mean over 3 seeds** (seed 0 / seed 1 / seed 2).

| arm | violations / sim | distinct fault-combination signatures (coarse) | fine patterns | policy-induced fine patterns (in scope) | sims to first violation |
|---|---|---|---|---|---|
| Muse-guided (closed loop) | 0.283 (0.323 / 0.267 / 0.260) | 15.7 (15 / 18 / 14) | 32.0 (31 / 37 / 28) | 15.0 (15 / 16 / 14) | 7.7 (4 / 9 / 10) |
| Muse rules-blind (closed loop) | 0.316 (0.341 / 0.280 / 0.327) | 16.3 (16 / 15 / 18) | 33.7 (32 / 28 / 41) | 17.3 (15 / 12 / 25) | 6.0 (5 / 9 / 4) |
| One-shot Muse bank (40) + random mutations | 0.142 (0.198 / 0.113 / 0.113) | 6.7 (6 / 6 / 8) | 11.0 (12 / 8 / 13) | 5.7 (6 / 3 / 8) | 10.0 (10 / 8 / 12) |
| Matched random: family + marginals | 0.307 (0.289 / 0.327 / 0.307) | 17.7 (16 / 19 / 18) | 35.3 (31 / 35 / 40) | 14.3 (12 / 15 / 16) | 2.0 (1 / 1 / 4) |
| Matched random: family only | 0.031 (0.030 / 0.037 / 0.027) | 4.0 (3 / 5 / 4) | 7.3 (6 / 11 / 5) | 6.0 (5 / 9 / 4) | 30.0 (10 / 1 / 79) |
| CMA-ES (closed loop) | 0.077 (0.185 / 0.037 / 0.010) | 1.7 (2 / 2 / 1) | 2.7 (4 / 3 / 1) | 2.7 (4 / 3 / 1) | 119.3 (4 / 197 / 157) |
| Plain random | 0.006 (0.009 / 0.007 / 0.003) | 1.3 (1 / 2 / 1) | 1.7 (2 / 2 / 1) | 0.7 (0 / 2 / 0) | 63.7 (10 / 15 / 166) |

Union over 3 seeds (distinct coarse signatures / fine patterns):

- Muse-guided (closed loop): 23 / 61
- Muse rules-blind (closed loop): 24 / 69
- One-shot Muse bank (40) + random mutations: 8 / 20
- Matched random: family + marginals: 21 / 67
- Matched random: family only: 6 / 15
- CMA-ES (closed loop): 3 / 5
- Plain random: 3 / 5

## Muse's empirical proposal distribution (784 Muse proposals, 3 seeds; 48 random fallbacks excluded)

| | Muse | plain random |
|---|---|---|
| two-wheel fault scenarios | 76.8% | 15.0% |
| RW fault count 0 / 1 / 2 | 7% / 17% / 77% | 39% / 46% / 15% |
| heater / leak present | 51% / 67% | 54% / 40% |
| RW severity = 1.0 (derate / friction) | 76% / 85% | ~0% (uniform 0.2-1.0) |
| median RW onset (fraction of run) | 0.009 | 0.40 (uniform 0-0.8) |
| median beta (deg) | 5 | 35 (uniform 0-70) |
| median heater W / leak Nm | 6.0 / 1.5e-06 | 3.5 / 9e-7 |

Full distribution: `data/matched/muse_distribution.json` (`python3 src/muse_distribution.py`).

## Arms

- **Matched random: family only** (`matchfam`): fault-kind combination (RW fault count + types, heater y/n, leak y/n) drawn from Muse's empirical joint combo distribution; wheel indices uniform; every continuous parameter uniform exactly as plain random. Open loop.
- **Matched random: family + marginals** (`matchall`): as above, but each continuous parameter is drawn independently from Muse's pooled empirical marginal (bootstrap of observed values). Open loop. These marginals are what Muse converged to *with* feedback, so this is an optimistic, hindsight-informed baseline: it only exists because Muse was run first.
- **One-shot Muse bank** (`oneshot`): one Muse call per seed (same system prompt as the Muse arm, no results ever shown) returns 40 scenarios; the remaining budget is plain random mutations of uniformly chosen bank members, no selection on outcomes. Provenance (model, response id, request id) in `data/matched/oneshot_seed*_bank.json`.
- Muse / Muse-blind / CMA-ES / plain random: stored runs in `data/cmp/`, re-scored under the corrected rule (rows rewritten by `src/satfix.py`; `src/matched_compare.py` re-simulated every row still carrying wheel_saturation as a cross-check and asserts attitude/battery outcomes are unchanged).

Coarse signature = earliest violation <- sorted fault kinds of the delta-debugged minimal counterexample; fine adds wheel index / leak axis. Counted only for minimized cases that reproduce.

One-shot bank calls:

- seed 0: 40/40 valid; model `muse-spark-1.3`, response_id `chatcmpl-01a1a562-2c75-7186-a462-85d2632221ad`, request_id `974170ef-ce73-43b3-a627-c292f28d1504`, 127.59 s
- seed 1: 40/40 valid; model `muse-spark-1.3`, response_id `chatcmpl-01a1a563-8213-7199-bad3-6c1c36d45252`, request_id `52a20dda-5ee1-4fe6-9566-392ff0c9dc50`, 86.4 s
- seed 2: 40/40 valid; model `muse-spark-1.3`, response_id `chatcmpl-01a1a565-1cba-7688-9ef0-58b317d66138`, request_id `3ab04a8e-8226-47f3-8009-b6eedae5983c`, 103.93 s

## Reproduce

```
python3 src/muse_distribution.py
bash data/matched/run_matched_chain.sh   # matchfam, matchall, oneshot (bank needs MUSE_API_KEY), then matched_compare
python3 src/matched_report.py
```

## Reading

READING_PLACEHOLDER
