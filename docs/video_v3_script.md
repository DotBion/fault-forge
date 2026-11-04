# FaultForge demo video v3: timed script

Generated from `demo/v3_script.py` (`python3 demo/v3_script.py`); edit there, not here.
Timings: nominal seconds, or the rendered length if `demo/vo_v3/durations.json` exists.
Narration: `demo/make_vo.py --script v3` (edge-tts en-US-AndrewNeural, piper fallback).
Gate facts counted from data/gated at generation time: 12 strict/structural proposals (12 rejected), 2 budget-mode proposals, accepted: ['b1t1'].

## s1  0:00-0:18  (18.4 s)  Before this week / this week / impact

**On screen:** Title. 'Before this week: Basilisk (open source) + our rule-based FDIR policy.' 'This week: Muse-guided search, minimizer, policy on/off check, gated repair loop.' Impact line on screen.

**Voiceover:** Before this week: Basilisk and a rule-based FDIR policy. This week: Muse-guided search and gated repair. FaultForge hands an FDIR team the multi-fault combinations a test campaign would miss, each as a one-command replay, with a candidate patch the gate has vetted.

## s2  0:18-0:29  (11.0 s)  Credibility: 568/576

**On screen:** 576-cell single-fault grid filling in -> '568 / 576'. Policy rules listed; 'structure follows published CubeSat FDIR, thresholds are ours'.

**Voiceover:** Four reaction wheels, published-style fault protection. Tested one fault at a time, it passes five hundred sixty-eight of five hundred seventy-six runs.

## s3  0:29-0:51  (22.0 s)  LIVE: make live (Muse role 1, scenario search)

**On screen:** Real asciinema take demo/live/take1.cast, unedited; banner 'LIVE · recorded <UTC/ET>'. The Muse wait is played faster with a burned-in 'SPED UP Nx' label; everything else real time; final frame held with a provenance callout (model, response id, x-request-id, latency).

**Voiceover:** This is a live, unedited run. Role one, scenario search: Muse Spark reads the policy and returns eight fault scenarios as structured JSON. The wait for the model is shown sped up, and labeled. Basilisk simulates all eight: two break a safety rule. Every live call logs its model id and request id.

## s4  0:51-1:07  (16.0 s)  Recorded calls: Muse roles 2 and 3 (diagnosis, patch proposal) + gate decision

**On screen:** Cards built verbatim from data/gated/r1t1_*.json and s1_*.json: diagnosis -> proposed patch JSON -> gate decision (computed by code). Label 'recorded call, first committed <ET>'; 'request id not logged'.

**Voiceover:** Roles two and three, from recorded calls. Muse diagnoses the minimized failures: the policy spends its only isolation on the first, mild fault. Then it proposes a patch, and the gate, not the model, decides.

## s5  1:07-1:19  (12.0 s)  Recorded call: rules-blind inference

**On screen:** Quote card, verbatim, data/cmp/museblind_seed1_calls.jsonl line 5 (round 4); 'recorded call, first committed <ET>'; ground truth shown beside it.

**Voiceover:** With the policy hidden from the prompt, blind Muse inferred the rule after four rounds: FDIR isolates at most one wheel, so dual derates leave a bad wheel active.

## s6  1:19-1:52  (33.0 s)  Headline a6e8087b: policy on vs off (same render as v2 s4)

**On screen:** Split-screen Basilisk replay of a6e8087b7a52c977: policy ON -> attitude loss (peak 180 deg); policy OFF -> survives (peak 16 deg).

**Voiceover:** Here's one Muse found, minimized to just two faults. Wheel zero picks up mild friction, and the policy isolates it, spending its only isolation. About seven minutes later, wheel one dies completely. Now it can't be isolated, the controller keeps commanding a dead wheel, and the spacecraft tumbles to a hundred and eighty degrees. Same faults, policy switched off: pointing never passes sixteen degrees. The safety logic caused this failure.

## s7  1:52-2:07  (15.0 s)  Chart 1: distinct coarse failure patterns per arm (3 seeds)

**On screen:** Bar chart: unique COARSE failure patterns per seed (mean + per-seed dots) for Muse-blind, Muse, CMA-ES, random from data/cmp/summary.json; sims-to-first-violation under each bar.

**Voiceover:** Over three seeds with equal budgets, both Muse arms find about twenty failure patterns; CMA-ES about two, random about one. Muse's first failure comes in about six simulations, CMA-ES's in about a hundred.

## s8  2:07-2:33  (25.9 s)  Gate: checks outside the model's control; chart 2 trend (auto-filled)  **AUTO-FILLED**

**On screen:** Gate diagram (patch -> re-simulate 3,508 runs -> decision -> rejection + regressions back to Muse), the true retry budgets, reject table (data/gated/rejects_table.md or the gate files), trend chart plots/gated_repair_trend.png [PLACEHOLDER until it exists].

**Voiceover:** Repairs face checks outside the model's control. Each Muse patch is re-simulated on thirty-five hundred stored runs, and each rejection, with its regressions, goes back to Muse: up to six proposals per round strict, four in budget mode. All twelve strict and structural proposals failed, each adding new violations. Then a budget-mode patch passed: thirteen fixes, no clean run broken.

## s9  2:33-2:48  (14.7 s)  Prior work + limits

**On screen:** Prior work boxes (LLM-Falsifier, NASA Orion GN&C FM verification) + 'new here'; limits list.

**Voiceover:** This builds on LLM-Falsifier and NASA's Orion fault-management verification. New here is an open, closed loop in a physics sim. Limits: a static Sun, no momentum dumping, and thresholds we chose.

## s10  2:48-2:53  (5.0 s)  Close

**On screen:** 'git clone … && make replay' (no key) / 'make live' (your key). Repo URL.

**Voiceover:** FaultForge. Clone it and run make replay. No key needed.

**Total: 2:53 (173.1 s)**, cap 175 s.

## Honesty notes

- s3 is a real, unedited terminal recording; only the model wait is played faster and it carries a burned-in 'SPED UP Nx' label. Take 2 (demo/live/take2.cast) found 0/8 violations; it is in the repo too.
- s4/s5 are recorded calls, labelled with the commit time the file was first committed; their request ids were not logged (logging was added in src/muse_client.py afterwards).
- The impact line only says 'a candidate patch the gate has vetted' once a gate file records an accept; until then it says every candidate patch is checked by the gate.
