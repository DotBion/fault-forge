# FaultForge demo video v4: timed script

Generated from `demo/v4_script.py` (`python3 demo/v4_script.py`); edit there, not here.
Timings: nominal seconds, or the rendered length if `demo/vo_v4/durations.json` exists.
Narration: `demo/make_vo.py --script v4` (edge-tts en-US-AndrewNeural, piper fallback).
Data at generation time: defects 276 cases (D1 254, D2 19, D3 3, tie-break 63); strict/structural proposals 12 (12 rejected); budget accepted: b1t1; matched random: not available (pending slot); fresh check: done.

## s1  0:00-0:36  (36.0 s)  The failure: minimized a6e8087b, full policy vs isolation-only suppressed

**On screen:** Split-screen Basilisk replay of minimized case a6e8087b (demo/data/hl4_*.csv): left full v1 policy (isolates RW0 at 120 s, cannot isolate dead RW1, attitude loss), right same policy with ONLY isolation suppressed. End card leads with the safety-rule metric: longest stretch > 30 deg 9,645 s vs 30 s (limit 1,200 s); 24-case sweep 24/24 vs 0/24; then peak 180 vs 137 deg with context. Footnote: minimized case; original run 173 also fails with the policy off.

**Voiceover:** Here's a minimized case Muse found: two faults. Wheel zero gets mild friction, and the policy isolates it, spending its only isolation. Minutes later wheel one dies; it can't be isolated, so it stays in the loop. On the right, the same policy with only isolation switched off. The rule: at most twenty minutes beyond thirty degrees. Full policy: nine thousand six hundred forty-five seconds in one stretch. Isolation off: thirty. Twenty-four nearby variants: twenty-four failures versus zero.

## s2  0:36-0:51  (14.8 s)  How FaultForge found it: Muse in labeled roles

**On screen:** Pipeline card: Muse roles labeled (1 scenario search, 2 blind rule inference, 3 diagnosis, 4 repair selection from an engineer-provided menu) vs code steps (Basilisk sim, minimizer, policy-off re-run, ablations, gate).

**Voiceover:** How FaultForge found it. Muse Spark has four labeled roles: scenario search, blind rule inference, diagnosis, and choosing a repair from an engineer-provided menu. Simulation, minimization and the gate are plain code.

## s3  0:51-1:12  (21.0 s)  LIVE take1 (Muse role 1) with request id

**On screen:** Real asciinema take demo/live/take1.cast, unedited except a labelled speed-up of the Muse wait; final provenance card with response id and x-request-id from data/live/live_2026-11-04T061215Z.json. Note: recorded (non-live) calls have no request ids.

**Voiceover:** This is a live, unedited run. Muse returns eight fault scenarios as JSON; the wait is sped up and labeled. Basilisk simulates all eight, and two break a safety rule. This live call logged its request id. The older recorded calls did not.

## s4  1:12-1:38  (26.0 s)  Defect classes D1-D3 + D4 tie-break bug, with counts and replay commands

**On screen:** Four cards from data/satfix/defects.json: D1 isolation lock-in 254, D2 isolates a still-needed wheel 19, D3 safe-mode chattering 3, D4 implementation bug: same-step threshold crossings resolved by wheel index, not residual, 63/276. Each with its replay command.

**Voiceover:** 276 policy-caused cases reduce to three defect classes. Isolation lock-in: 254. Isolating a wheel that is still needed: nineteen. Safe-mode chattering: three. And FaultForge surfaced a bug in the policy itself: when two wheels cross the threshold in the same step, it picks by wheel index, not residual. 63 cases. Each has a one-command replay.

## s5  1:38-2:02  (24.1 s)  Chart 1: benchmarks (viol/sim, coarse signatures, matched-random slot)

**On screen:** Chart 1 (two panels, data/cmp/summary.json): violations per sim per arm (Muse 0.283, random 0.006, ~46x) and distinct fault-combination signatures (coarse; Muse 15.7 vs CMA-ES 1.7). A clearly marked MATCHED RANDOM slot: filled from data/matched/summary.json if it exists at render time, else 'pending'. Blind-vs-informed labelled hypothesis.

**Voiceover:** Against baselines, equal budgets, three seeds: Muse finds 0.283 violations per simulation, random 0.006, about 46 times more. Muse finds about 16 distinct fault-combination signatures; CMA-ES under two. A random baseline matched to Muse's fault families is still running; its slot is marked pending.

## s6  2:02-2:36  (33.7 s)  The gate: strict rejects all; budget accepts b1t1; fresh result; chart 2

**On screen:** Two gates side by side: STRICT (0 new violations) rejected all N; BUDGET (net > 0, <= 3 clean runs broken) accepted b1t1 wheel_safe_frac 0.97 / 60 s: 26 fixes, net +24, 1 clean run broken (museblind_seed1_28, waived), round 2 rejected. Then chart 2 plots/gated_repair_trend.png with the fresh-search result.

**Voiceover:** Repair. Muse selects and parameterizes from an engineer-provided menu, and code decides. The strict gate, zero new violations, rejected all twelve proposals. The budget gate accepted one: twenty-six fixes, net plus twenty-four, and one clean run broken, named and waived. On fresh data, a new Muse search breaks the patch in 31 of 100 runs, versus 38 before, unpaired. On the same 300 held-out scenarios, four are fixed and none broken. A modest cut.

## s7  2:36-2:53  (17.0 s)  Limits + related work + close

**On screen:** Limits list; related work (LLM-Falsifier arXiv 2609.20752, NASA Orion FM verification); 'implemented', not 'first'; close: git clone ... && make replay.

**Voiceover:** Limits: one simulated spacecraft, no momentum dumping, thresholds we chose, and blind versus informed search is still a hypothesis. This builds on LLM-Falsifier; we implemented the loop for fault protection. Clone it and run make replay.

**Total: 2:52 (172.6 s)**, cap 175 s.

## Honesty notes

- s1 is a minimized case; the original Muse run (seed 1, run 173) also fails with the policy off. The right panel changes ONE thing (suppress_isolation). Its peak error (137 deg) is shown only after the safety-rule metric, with the note that the craft tumbles through safe mode but recovers within the limit.
- s3 is a real, unedited terminal recording; only the model wait is sped up, with a burned-in label. Only this live call has a request id; recorded calls (search/repair logs) have none.
- s4 counts are ablation classes of 276 minimized cases; D4 is a code bug in our policy, reported, not fixed.
- s5 signatures are fault-combination counts, not defects. Random is i.i.d. over the whole space; the matched random slot is filled only from data/matched/summary.json.
- s6 describes the strict and budget gates separately; the budget gate accepts by design up to 3 broken clean runs per patch. Only one budget round was accepted (1 waiver in total).
