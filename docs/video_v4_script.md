# FaultForge demo video v4: timed script

Generated from `demo/v4_script.py` (`python3 demo/v4_script.py`); edit there, not here.
Timings: nominal seconds, or the rendered length if `demo/vo_v4/durations.json` exists.
Narration: `demo/make_vo.py --script v4` (edge-tts en-US-AndrewNeural).
Data at generation time: defects 276 cases (D1 254, D2 19, D3 3, tie-break 63); strict/structural proposals 12 (12 rejected); budget accepted: b1t1; matched random: included (data/matched/summary.json); fresh check: done.

## s1  0:00-0:40  (40.0 s)  The failure: minimized a6e8087b, full policy vs isolation-only suppressed

**On screen:** Opening card (no hash, no 'minimized'): 'A spacecraft's own recovery logic can turn a survivable fault combination into a lost one. FaultForge finds those cases.' Then split-screen Basilisk replay of minimized case a6e8087b (demo/data/hl4_*.csv): left full v1 policy (isolates RW0 at 120 s, cannot isolate dead RW1, attitude loss), right same policy with ONLY isolation suppressed. End card leads with the safety-rule metric: longest stretch > 30 deg 9,645 s vs 30 s (limit 1,200 s); 24-case sweep 24/24 vs 0/24; then peak 180 vs 137 deg with context. Footnote: minimized case; original run 173 also fails with the policy off.

**Voiceover:** A spacecraft's own recovery logic can turn a survivable fault combination into a lost one. FaultForge finds those cases. Here's one, minimized to two faults. Wheel zero gets mild friction; the policy isolates it, spending its only isolation. Then wheel one dies, and can't be isolated. On the right, only isolation is switched off. The limit: twenty minutes past thirty degrees. Full policy: nine thousand six hundred forty-five seconds. Isolation off: thirty. Nearby variants: twenty-four of twenty-four fail, versus zero.

## s2  0:40-0:55  (14.8 s)  How FaultForge found it: Muse in labeled roles

**On screen:** Pipeline card: Muse roles labeled (1 scenario search, 2 blind rule inference, 3 diagnosis, 4 repair selection from an engineer-provided menu) vs code steps (Basilisk sim, minimizer, policy-off re-run, ablations, gate).

**Voiceover:** How FaultForge found it. Muse Spark has four labeled roles: scenario search, blind rule inference, diagnosis, and choosing a repair from an engineer-provided menu. Simulation, minimization and the gate are plain code.

## s3  0:55-1:16  (21.0 s)  LIVE take1 (Muse role 1) with request id

**On screen:** Real asciinema take demo/live/take1.cast, unedited except a labelled speed-up of the Muse wait; final provenance card: main text 'Muse proposed 8 tests -> sim found 2 failures' (counted from the live JSON), small footer with model, endpoint, response id and x-request-id from data/live/live_2026-11-04T061215Z.json. Note: recorded (non-live) calls have no request ids.

**Voiceover:** This is a live, unedited run. Muse proposes eight fault scenarios as JSON; the wait is sped up and labeled. Basilisk simulates all eight, and two break a safety rule. The request id is in the footer; the older recorded calls have none.

## s4  1:16-1:42  (26.0 s)  Defect classes D1-D3 + D4 tie-break bug, with counts and replay commands

**On screen:** Four cards from data/satfix/defects.json: D1 isolation lock-in 254, D2 isolates a still-needed wheel 19, D3 safe-mode chattering 3, D4 implementation bug: same-step threshold crossings resolved by wheel index, not residual, 63/276. Each with its replay command.

**Voiceover:** 276 policy-caused cases reduce to three defect classes. Isolation lock-in: 254. Isolating a wheel that is still needed: nineteen. Safe-mode chattering: three. And FaultForge surfaced a bug in the policy itself: when two wheels cross the threshold in the same step, it picks by wheel index, not residual. 63 cases. Each has a one-command replay.

## s5  1:42-2:04  (22.0 s)  Chart 1: benchmarks, 4 bars (random, one-shot Muse bank, adaptive Muse, matched random)

**On screen:** One panel, violations per sim (data/cmp/summary.json + data/matched/summary.json), exactly 4 bars: plain random, one Muse call + random mutations (no feedback), adaptive closed-loop Muse, and marginals-matched random labelled 'samples Muse's learned distribution (needs finished Muse runs)'. Footnote: CMA-ES, family-only random, rules-blind Muse (hypothesis). Takeaway: Muse's closed loop discovers where failures live.

**Voiceover:** Violations per simulation, equal budgets. Random: 0.006. One Muse call plus mutations: 0.14. Muse's closed loop: 0.28. Sampling from Muse's finished proposals ties it, but needs those runs first. Muse's closed loop discovers where failures live.

## s6  2:04-2:28  (24.3 s)  Repair: held-out result first, then strict vs budget gate with the suite arithmetic

**On screen:** Banner: 'Held-out: 4 fixed, 0 newly broken' (same 300 scenarios, v1 vs b1t1, paired). STRICT gate (0 new violations) rejected all N. BUDGET gate accepted b1t1 wheel_safe_frac 0.97 / 60 s: fixed 26 suite runs; 2 runs gained a new violation (1 already failing, 1 previously clean) -> net 26 - 2 = +24; 1 clean run broken (museblind_seed1_28, waived). The unpaired fresh-search 38 -> 31 is README-only.

**Voiceover:** Repair. On three hundred held-out scenarios, the accepted patch fixes four and breaks none. Muse picks from an engineer-provided menu; code decides. The strict gate rejected all twelve proposals. The budget gate accepted one: twenty-six suite runs fixed, two gained a new violation, net plus twenty-four. One was clean before; it's named and waived.

## s7  2:28-2:47  (18.6 s)  Limits + related work + close

**On screen:** Three limits + 'More in README'; related work (LLM-Falsifier arXiv 2609.20752, NASA Orion FM verification); 'implemented', not 'first'; close: git clone ... && make replay.

**Voiceover:** Limits: one simulated spacecraft and our own policy; a sampler matched to Muse's proposals ties it once the region is known; and the single-fault grid is the policy's own acceptance test. More in the README. This builds on LLM-Falsifier. Clone it and run make replay.

**Total: 2:46 (166.6 s)**, cap 175 s.

## Honesty notes

- s1 is a minimized case; the original Muse run (seed 1, run 173) also fails with the policy off. The right panel changes ONE thing (suppress_isolation). Its peak error (137 deg) is shown only after the safety-rule metric, with the note that the craft tumbles through safe mode but recovers within the limit.
- s3 is a real, unedited terminal recording; only the model wait is sped up, with a burned-in label. Only this live call has a request id; recorded calls (search/repair logs) have none.
- s4 counts are ablation classes of 276 minimized cases; D4 is a code bug in our policy, reported, not fixed.
- s5 signatures are fault-combination counts, not defects. Random is i.i.d. over the whole space; the matched random bars are filled only from data/matched/summary.json. MATCHED fam.+params samples each parameter from the marginals of Muse's own proposals, so it is a hindsight-informed baseline, not an independent method.
- s6 describes the strict and budget gates separately; the budget gate accepts by design up to 3 broken clean runs per patch. Only one budget round was accepted (1 waiver in total). Net +24 = 26 fixed - 2 runs with a new violation (museblind_seed1_121 was already failing, museblind_seed1_28 was clean). The unpaired fresh-search numbers (38 -> 31 of 100) are in the README, not the video.
