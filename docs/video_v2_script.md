# FaultForge demo video v2: timed script

Generated from `demo/v2_script.py` (`python3 demo/v2_script.py`); edit there, not here.
Timings: nominal seconds, or the actual rendered length if `demo/vo/durations.json` exists.
Narration: `demo/make_vo.py` (edge-tts en-US-AndrewNeural, piper en_US-ryan-high fallback).
Segments marked **PENDING** hold placeholders for the gated-repair results (expected ~9 AM ET Nov 4).

## s1  0:00-0:13  (12.8 s)  Title: existed before / built this week

**On screen:** Star field. 'FaultForge' + tagline. Two lines: 'Existed before: Basilisk spacecraft simulator (open source) and the Meta Muse Spark API.' / 'Built this week: fault harness, FDIR safe-mode policy, Muse-guided search, minimizer, policy on/off causal check, gated repair loop.'

**Voiceover:** Before this week, there was Basilisk, an open-source spacecraft simulator. This week we built FaultForge, where Meta's Muse Spark hunts for failures caused by a spacecraft's own safety logic.

## s2  0:13-0:30  (17.7 s)  Credibility: the policy passes single-fault testing

**On screen:** 576-cell grid filling green/red (data/grid.jsonl) -> '568 / 576'. Footer: 'Policy structure follows published CubeSat FDIR (EUCASS 2019, NASA SWEHB 9.07, ECSS-E-ST-60-30C). Thresholds are ours.' Small spec list: torque-residual FDIR 3e-4 Nm, 1 isolation max, safe mode at 15 deg/120 s.

**Voiceover:** Our CubeSat has four reaction wheels and fault protection built like published designs: detect a bad wheel, isolate it, fall back to safe mode. Tested one fault at a time, it passes five hundred sixty-eight of five hundred seventy-six runs. It looks safe.

## s3  0:30-0:57  (27.0 s)  Search race: Muse vs CMA-ES vs random (3 seeds)

**On screen:** Animated cumulative-violation race, seed 1, 300 sims per arm (data/cmp/*_seed1.jsonl). Then plots/arms_comparison.png (3 seeds) with a callout row: viol/sim and sims-to-first-violation per arm (data/cmp/summary.json, or blind_3seed_prelim.json until compare.py finishes).

**Voiceover:** But real failures stack. So we race four searchers on the same budget. Muse Spark reads every result and proposes the next fault scenarios. Muse finds its first failure in about six simulations; CMA-ES needs about a hundred. Across three seeds, a third of Muse's runs end in a safety violation. CMA-ES manages one in twelve, random under one in a hundred.

## s4  0:57-1:30  (33.0 s)  Headline replay a6e8087b: policy on vs off

**On screen:** Split screen, Basilisk replay of minimized case a6e8087b7a52c977 (found by Muse, muse_seed1_173): 3D spacecraft + boresight, event ticker, attitude-error strip with 30 deg bound, wheel speeds. Left: policy ON -> ATTITUDE LOSS (peak 180 deg). Right: policy OFF -> SURVIVES (peak 16 deg). Closing caption: 'The policy causes the failure: it spends its one isolation on the MILD wheel.'

**Voiceover:** Here's one Muse found, minimized to just two faults. Wheel zero picks up mild friction, and the policy isolates it, spending its only isolation. About seven minutes later, wheel one dies completely. Now it can't be isolated, the controller keeps commanding a dead wheel, and the spacecraft tumbles to a hundred and eighty degrees. Same faults, policy switched off: pointing never passes sixteen degrees. The safety logic caused this failure.

## s5  1:30-1:53  (22.5 s)  Blind inference: Muse works out the hidden rule

**On screen:** Quote card, verbatim Muse analysis from data/cmp/museblind_seed1_calls.jsonl line 5 (round 4): 'FDIR isolates at most one wheel so dual derates leave a bad wheel active...' Then per-seed bars Muse vs Muse-blind viol/sim. Caption: 'Hypothesis (untested): the rules anchor informed Muse to expected failure modes.'

**Voiceover:** And Muse didn't need the rules. In a blind run, with the policy's logic hidden, it wrote this after four rounds: FDIR isolates at most one wheel, so dual derates leave a bad wheel active. Blind Muse found more failures than informed Muse on all three seeds. Our hypothesis: knowing the rules anchors it to the failures it expects.

## s6  1:53-2:17  (24.0 s)  Repair loop with a regression gate (PLACEHOLDERS)  **PENDING**

**On screen:** (a) Gate diagram: Muse patch -> replay ~3,500 stored runs -> accept only if no previously clean run breaks. (b) Strict-gate reject table from data/gated/rejects_table.md [PLACEHOLDER card until it exists]. (c) plots/gated_repair_trend.png, measured on FRESH held-out searches [PLACEHOLDER]. (d) Waiver list from data/gated/waivers.md, each broken run listed and replayable [PLACEHOLDER].

**Voiceover:** Then Muse proposes fixes, and every patch faces a gate: replay about thirty-five hundred stored runs, and nothing that was safe may break. The gate rejected every parameter-only patch, because each one traded one failure for another. [Result of the structural and waiver rounds goes here.] Progress is measured on fresh searches, never on the gate's own test set.

## s7  2:17-2:35  (17.7 s)  Prior work and what's new

**On screen:** Two cited boxes: 'LLM-Falsifier (arXiv 2609.20752, 2026): LLM-guided falsification of controllers' and 'NASA Orion GN&C fault-management verification'. Below: 'New here: an open-source closed loop: find -> minimize -> policy on/off causal check -> patch -> re-test, in a physics sim.'

**Voiceover:** This builds on prior work: LLM-Falsifier falsifies controllers with language models, and NASA verifies Orion's fault management at scale. What's new is an open, closed loop: find, minimize, prove the policy is the cause, then patch and re-test.

## s8  2:35-2:44  (9.4 s)  Limits

**On screen:** Limits slide: static Sun direction; no momentum dumping; self-written policy (structure follows published FDIR, thresholds are ours); one spacecraft model, 2-orbit runs.

**Voiceover:** Limits: a static Sun, no momentum dumping, and a policy we wrote ourselves: published structure, our own thresholds.

## s9  2:44-2:54  (9.7 s)  Close

**On screen:** 'Find -> minimize -> explain -> repair -> re-test'. Replay command for the headline case. Repo URL. 'Basilisk · Meta Muse Spark · CMA-ES & random baselines'.

**Voiceover:** FaultForge: find, minimize, explain, repair, re-test. Every result in this video replays from the public repo.

**Total: 2:53 (173.8 s)**, cap 178 s.

## Notes

- The required opening line is in s1 (on screen and spoken).
- Muse's words 'defeats' / 'evade' appear only in verbatim on-screen quotes; narration never uses them.
- 'Blind finds more' is stated as a result; the reason is explicitly a hypothesis.
- Before final: replace the bracketed s6 sentence with the real outcome (structural rule accepted? waiver count? fresh-search trend down?), then re-run `bash demo/render_v2.sh`.
