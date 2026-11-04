# Demo video v2: candidate headline cases and Muse reasoning lines

Selection: minimized counterexamples from `data/cmp/minimized.jsonl` whose source runs come **only** from Muse arms
(`muse_*` or `museblind_*`, none from CMA-ES or random), that reproduce, are **policy-induced** (the violation is gone
with the policy disabled), and are in scope (not two near-dead wheels). That gives 146 cases, which were re-run with and
without the policy (`src/video_candidates.py` -> `data/video_candidates_runs.jsonl`) and ranked by how visible the
breach is (peak attitude error x out-of-bounds duration), preferring 2-fault cases with a clean policy-off run.
"Policy off" = same faults, recovery policy disabled. All five are fixed (clean) by the repaired policy v2.

| # | key (minimized) | found by (run id) | faults (minimized) | with v1 policy | policy off |
|---|---|---|---|---|---|
| 1 | `a6e8087b7a52c977` | Muse, `muse_seed1_173` | beta 65, f0 255; rw0 friction 0.2 @105 s; rw1 torque_derate 1.0 (dead) @505 s | attitude_loss @2915 s; peak err 180 deg; out-of-bounds 8.0x the 1200 s limit | clean (peak 16 deg) |
| 2 | `e8fd162c060f9b0e` | **Muse-blind** (policy rules hidden), `museblind_seed1_134` | beta 5, f0 150; rw0 friction 0.2 @0; rw2 torque_derate 1.0 (dead) @0 | attitude_loss @2105 s; peak 148 deg; 7.2x limit | clean (peak 16 deg) |
| 3 | `261b5b8b17961c8d` | Muse, `muse_seed2_247` | beta 0.5, f0 85; rw1 friction 0.2 @30 s; rw2 friction 0.7 @30 s | attitude_loss @6395 s; peak 158 deg; 5.1x limit | clean (peak 16.5 deg) |
| 4 | `89603c39d8bf9db7` | Muse, `muse_seed0_29` | beta 22, f0 330; rw3 (skew) torque_derate 1.0 @100 s; leak 3e-7 Nm along (1,1,1) @100 s; rw1 friction 0.2 @150 s | attitude_loss @2440 s AND wheel_saturation @10375 s; peak 180 deg; 4.1x limit; policy cycles SAFE/NOMINAL 8 times | clean (peak 15 deg) |
| 5 | `92f4e68bfc3b95cf` | **Muse-blind**, `museblind_seed1_270` | beta 0, f0 180; rw0 torque_derate 0.975 @0; rw1 friction 0.75 @0 | attitude_loss @7370 s; peak 142 deg; 2.9x limit; 7 SAFE/NOMINAL cycles | clean (peak **4.7 deg**) |

One-line stories (from the v1 policy logs):
1. **Best headline.** A mild 20% friction on wheel 0 trips FDIR at t=120 s, which uses up the policy's only isolation. When wheel 1 dies completely at t=505 s it can't be isolated, so the controller keeps commanding a dead wheel and the spacecraft tumbles to 180 deg. Without the policy, all 4 wheels stay in use and pointing never exceeds 16 deg.
2. Same mechanism, found by Muse **without being told the rules**: the mild-friction wheel 0 is isolated at t=15 s, the dead wheel 2 stays in the control loop, and attitude is lost for 7x the allowed time. Policy off: 16 deg peak.
3. Mis-isolation with two friction faults: FDIR removes the *milder* wheel 1 (20%) at t=45 s and is then stuck with the heavier 70% friction wheel 2. The result is attitude loss for 5x the limit, while policy off stays at 16 deg.
4. Leak along the skew axis, the skew wheel dead, and mild friction on wheel 1: FDIR isolates the mild wheel 1, the dead skew wheel can't be isolated, and the policy flaps SAFE<->NOMINAL eight times. The run ends with both attitude loss and wheel saturation (policy off: 15 deg peak). Good for showing "the policy makes it worse".
5. The policy isolates the right wheel (near-dead wheel 0), but with the remaining 75%-friction wheel 1 it can't hold 30 deg, and it oscillates SAFE<->NOMINAL for 3 h. With the policy off, the near-dead wheel still helps a little and error stays at **4.7 deg**. This is the starkest on/off contrast, but the visual is less dramatic.

Honorable mention (dramatic but not clean with the policy off): `505563eb402294cf` (`muse_seed0_139`, Z leak + rw2 friction). It reaches a 163 deg attitude loss with the policy, but wheel saturation still occurs with the policy off.

## Muse reasoning: inferring the one-wheel-isolation rule (rules-blind run, seed 1)

In the rules-blind prompt the policy was described only qualitatively ("a wheel ... may be isolated"), with no
thresholds and no mention of the one-isolation limit (`src/llm_search.py` lines 149-160, `system_text_blind`). Per-run
`isolated_wheels` was reported back, so the rule was inferred from observed outcomes, not given.

- **`data/cmp/museblind_seed1_calls.jsonl`, line 5 (round 4), field `analysis`, verbatim:**
  > "FDIR isolates at most one wheel so dual derates leave a bad wheel active. Friction pair 2/3 looks resilient, 0/1 untested. Battery thinnest for heater plus friction at beta~0. Partial and staggered onsets evade isolation. Probe boundaries and novel no-RW, partial, staggered cases."
- Same response, scenario hypothesis (run `museblind_seed1_36`, **`data/cmp/museblind_seed1.jsonl` line 37**, violated attitude_loss), verbatim:
  > "Staggered X Y wheel losses with persistent leak defeats sequential isolation"
- Earlier probe that led to it (`museblind_seed1_calls.jsonl` line 3, round 2, `analysis`), verbatim:
  > "Refine three near-miss wheel/battery edges, align leaks with degraded axes, probe minimal single-wheel failures, staggered second faults and late heaters to defeat FDIR and drain eclipse power."
- Run-level hypotheses in rounds 1-3 (`museblind_seed1.jsonl` lines 13, 23, 30), verbatim: "Mixed derate-friction on X-skew with diagonal leak defeats isolation" (violated), "Staggered second wheel failure during leak recovery loses attitude", "Mixed X derate plus Y friction with X leak confuses isolation" (violated).

Video caution: "defeats" / "evade" are Muse's words. Quote them verbatim on screen, but use "stress-test" in your own narration.
