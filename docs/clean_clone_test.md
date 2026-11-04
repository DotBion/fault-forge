# Clean-clone test

Fresh `git clone` of the public repo into an empty directory (`/workspace/cc_test`), fresh venv, following only the
README quickstart. Run on 2026-11-04 ~1:10 AM ET, Debian, Python 3.13.5, unauthenticated clone.

Result: **PASS**. `env -u MUSE_API_KEY make replay` succeeds without any key (exit 0, 5 s). `make live` succeeds with
the key supplied only via `.env` (exit 0, 48 s) and prints model id, endpoint, response id and x-request-id.

History of runs:
1. Pass 1 (commit bdf21c0): replay and live both passed. Colour escape codes showed up in piped output, so NO_COLOR is
   now honoured (commit 80e4050). Also checked: `make live` with no key anywhere exits 2 with
   "MUSE_API_KEY not set: cp .env.example .env and fill it in (or export it)".
2. Pass 2 (commit 80e4050): full transcript below (unedited apart from this header; the key value was never printed,
   and `.env` was deleted afterwards). Before this test the box had no `make`; it was installed from the Debian
   package (`make 4.4.1`), since the README assumes GNU make.

```text
$ git clone https://github.com/DotBion/meta-hack.git faultforge && cd faultforge
(HEAD 80e4050 replay/live: honour NO_COLOR, timing text)
$ python3 --version
Python 3.13.5
$ python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(installed: bsk==2.12.1 cma==4.5.0 matplotlib==3.10.9 numpy==2.4.6 pandas==3.0.3 )
$ env -u MUSE_API_KEY make replay
== 1. Headline counterexample a6e8087b7a52c977 (re-simulated now in Basilisk, a few seconds) ==
  pattern: attitude_loss <- rw0_friction+rw1_torque_derate   minimized in 11 sims
  faults : rw0 friction sev 0.2 @ 105s; rw1 torque_derate sev 1.0 @ 505s;  beta 65.0 deg
  policy ON : VIOLATION {'attitude_loss': 2915.0}   peak attitude error after grace 179.9 deg
      margins: att_err 6.00x bound (30 deg), att_dur 8.04x limit (1200 s), wheel 1.04x sat, battery +0.450 SoC
      t=   105s  FAULT rw0 applied {"wheel": 0, "onset_s": 105.0, "type": "friction", "severity": 0.2}
      t=   120s  POLICY FDIR: wheel 0 isolated (residual 3.99e-04 Nm)
      t=   505s  FAULT rw1 applied {"wheel": 1, "onset_s": 505.0, "type": "torque_derate", "severity": 1.0}
      t=   930s  POLICY -> SAFE (sun-point, payload off): attitude error 138.2 deg > 15.0 for 120s
      t=  1530s  POLICY -> NOMINAL (SoC 0.80)
      t=  1650s  POLICY -> SAFE (sun-point, payload off): attitude error 51.5 deg > 15.0 for 120s
  policy OFF: no violation   peak attitude error after grace 16.2 deg
      margins: att_err 0.54x bound (30 deg), att_dur 0.00x limit (1200 s), wheel 0.34x sat, battery +0.178 SoC
      t=   105s  FAULT rw0 applied {"wheel": 0, "onset_s": 105.0, "type": "friction", "severity": 0.2}
      t=   505s  FAULT rw1 applied {"wheel": 1, "onset_s": 505.0, "type": "torque_derate", "severity": 1.0}
  => REPRODUCED: the FDIR policy itself causes the loss of attitude (policy-induced = True in data/cmp/minimized.jsonl)

== 2. Recorded Muse SEARCH call that proposed it (role: scenario search) ==
  model muse-spark-1.3 (run config; per-call model id/request id not logged in search logs)
  source data/cmp/muse_seed1_calls.jsonl line 22 (round 21), latency 54.2 s, tokens 20504; first committed 2026-10-30T06:00:44-04:00 (commit 1c915c4)
  Muse analysis:
      Refine four borderline clusters (rw1-rw3 sat, partial-derate battery, single-friction battery,
      rw2-rw3 friction) to cross thresholds and probe four uncovered combos: pure rw0-rw3, swapped
      mixed pair, heater-leak alone, leak-aligned single friction.
  proposed scenario (verbatim JSON):
      {"hypothesis": "Mixed friction-derate on X-Y wheels defeats control", "orbit": {"beta_deg":
      65.0, "f0_deg": 255.0}, "rw_faults": [{"wheel": 0, "onset_s": 105.0, "type": "friction",
      "severity": 1.0}, {"wheel": 1, "onset_s": 505.0, "type": "torque_derate", "severity": 1.0}],
      "heater": null, "torque_leak": null}
  -> sim run 173: violations {'attitude_loss': 2915.0}

== 3. Recorded rules-BLIND call (role: blind rule inference; policy text NOT in prompt) ==
  model muse-spark-1.3; data/cmp/museblind_seed1_calls.jsonl line 5 (round 4), latency 22.2 s; first committed 2026-10-30T07:06:09-04:00 (commit 35227f2)
      "FDIR isolates at most one wheel so dual derates leave a bad wheel active. Friction pair 2/3
      looks resilient, 0/1 untested. Battery thinnest for heater plus friction at beta~0. Partial
      and staggered onsets evade isolation. Probe boundaries and novel no-RW, partial, staggered
      cases."
  (ground truth, never shown to it: fdir isolates at most one wheel, min_avail = 3)

== 4. Recorded gated-repair calls (roles: diagnosis, patch proposal) + gate decisions ==
  r1t1 model muse-spark-1.3 latency 56s request id: not logged; first committed 2026-11-03T23:13:09-05:00 (commit 82058c1)
    diagnosis:
      FDIR allows only one isolation and latches the first wheel to exceed residual threshold. Mild
      friction severity 0.2 gives ~0.45 mNm residual just above 0.3 mNm threshold and often trips
      first. A later more severe friction/derate then cannot be isolated, leaving the worse wheel in
      the active set while the healthier wheel sits isolated, reducing controllability and causing
      attitude-loss/saturation that no-FDIR avoids.
    patch proposed: {"isolation_swap": true, "swap_ratio": 2.0}
    gate: reject - rejected: 20 new violations in 20 runs (20 previously clean) (evaluation stopped early after 861 runs)
  r1t2 model muse-spark-1.3 latency 83s request id: not logged; first committed 2026-11-03T23:13:09-05:00 (commit 82058c1)
    patch proposed: {"fdir_abs_Nm": 0.0006}
    gate: reject - rejected: 20 new violations in 20 runs (12 previously clean) (evaluation stopped early after 1777 runs)
  r1t3 model muse-spark-1.3 latency 192s request id: not logged; first committed 2026-11-03T23:13:09-05:00 (commit 82058c1)
    patch proposed: {"resume_min_s": 900.0}
    gate: reject - rejected: 19 new violations in 18 runs (10 previously clean) vs 44 fixes on the full suite
  r1t4 model muse-spark-1.3 latency 115s request id: not logged; first committed 2026-11-03T23:13:09-05:00 (commit 82058c1)
    patch proposed: {"att_safe_deg": 18.0}
    gate: reject - rejected: 6 new violations in 5 runs (4 previously clean) (evaluation stopped early after 982 runs)
  r1t5 model muse-spark-1.3 latency 69s request id: not logged; first committed 2026-11-04T00:25:14-05:00 (commit 0116465)
    patch proposed: {"isolation_swap": true, "swap_ratio": 2.5, "swap_min_res_Nm": 0.001, "swap_max_iso_res_Nm": 0.0006}
    gate: reject - rejected: 3 new violations in 3 runs (3 previously clean) (evaluation stopped early after 7 runs)
  r1t6 model muse-spark-1.3 latency 105s request id: not logged; first committed 2026-11-04T00:25:14-05:00 (commit 0116465)
    patch proposed: {"isolation_swap": true, "swap_ratio": 5.0, "swap_min_res_Nm": 0.002, "swap_max_iso_res_Nm": 0.0004}
    gate: reject - rejected: 3 new violations in 3 runs (3 previously clean) (evaluation stopped early after 25 runs)
  r2t1 model muse-spark-1.3 latency 44s request id: not logged; first committed 2026-11-04T00:25:14-05:00 (commit 0116465)
    patch proposed: {"isolation_swap": true, "swap_ratio": 2.0, "swap_min_res_Nm": 0.0008, "swap_max_iso_res_Nm": 0.0006}
    gate: reject - rejected: 3 new violations in 3 runs (3 previously clean) (evaluation stopped early after 66 runs)
  r2t2 model muse-spark-1.3 latency 81s request id: not logged; first committed 2026-11-04T00:24:27-05:00 (commit 9451b85)
    patch proposed: {"wheel_safe_frac": 0.97, "wheel_safe_s": 60.0}
    gate: reject - rejected: 1 new violations in 1 runs (0 previously clean) vs 13 fixes on the full suite
  r2t3 model muse-spark-1.3 latency 115s request id: not logged; first committed 2026-11-04T00:25:14-05:00 (commit 0116465)
    patch proposed: {"wheel_safe_frac": 0.97, "wheel_safe_s": 120.0}
    gate: reject - rejected: 2 new violations in 2 runs (0 previously clean) vs 9 fixes on the full suite
  r2t4 model muse-spark-1.3 latency 99s request id: not logged; first committed 2026-11-04T00:25:14-05:00 (commit 0116465)
    patch proposed: {"fdir_persist": 4}
    gate: reject - rejected: 3 new violations in 3 runs (3 previously clean) (evaluation stopped early after 13 runs)
  s1 model muse-spark-1.3 latency 61s request id: not logged; first committed 2026-11-04T00:58:51-05:00 (commit 226d087)
    diagnosis:
      Current FDIR allows only one isolation. Logs show first mild friction fault with residual
      ~4.5e-04 Nm trips detector and consumes the slot, then a later severe friction or torque-
      derate fault cannot be isolated. Control remains on three wheels including the badly degraded
      wheel, leading to attitude loss or wheel saturation, while no-isolation runs stay safe. This
      is policy-induced lock-in, dominant in rw_friction+rw_friction cases.
    patch proposed: {"fdir_readmit_s": 1800.0}
    gate: reject - rejected (strict): 3 new violations in 3 runs (3 previously clean), 1 fixes, 663 runs evaluated (stopped early)
  s2 model muse-spark-1.3 latency 44s request id: not logged; first committed 2026-11-04T00:58:51-05:00 (commit 226d087)
    patch proposed: {"fdir_hard_Nm": 0.0005}
    gate: reject - rejected (strict): 3 new violations in 3 runs (3 previously clean), 3 fixes, 794 runs evaluated (stopped early)
  gate = checks the model does not control: every candidate is re-simulated on the full suite (576-case grid + 2,932 stored search runs); rejections are fed back to Muse for the next try

replay done (no API key used).
(exit 0, 5 s)
$ cp .env.example .env   # then MUSE_API_KEY=<key> written into .env (value not shown)
$ env -u MUSE_API_KEY make live      # key comes only from .env
FaultForge live round  policy v1 (rules given)  8 scenarios  seed 72662
[muse] POST https://api.meta.ai/v1/chat/completions  model=muse-spark-1.3  json_mode  (3552 prompt chars) ...
[muse] HTTP 200 in 37.5 s  tokens 5856
[muse] analysis: "Probing distinct policy limits: single-isolation quota, sub-threshold friction, momentum capacity without dumping, safe-mode energy balance in eclipse, and synergistic faults. Varying beta, phasing, onset timing, axes to separate battery, attitude, saturation mechanisms."
[muse] scenario 0: {"hypothesis":"Two dead wheels leave underactuated control causing attitude loss","orbit":{"beta_deg":60.0,"f0_deg":0.0},"rw_faults":[{"wheel":0,"onset_s":100.0,"type":"torque_derate","severity":1.0},{"wheel":1,"onset_s":100.0,"type":"torque_derate","severity":1.0}],"heater":null,"torque_leak":null}
[muse] scenario 1: {"hypothesis":"Dead wheel plus secular leak exceeds remaining momentum capacity","orbit":{"beta_deg":50.0,"f0_deg":180.0},"rw_faults":[{"wheel":3,"onset_s":0.0,"type":"torque_derate","severity":1.0}],"heater":null,"torque_leak":{"onset_s":0.0,"mag_Nm":1.5e-06,"axis":[0.0,1.0,0.0]}}
[muse] scenario 2: {"hypothesis":"Moderate friction evades FDIR while wasting power and degrading pointing","orbit":{"beta_deg":0.0,"f0_deg":90.0},"rw_faults":[{"wheel":0,"onset_s":0.0,"type":"friction","severity":0.4},{"wheel":1,"onset_s":0.0,"type":"friction","severity":0.4}],"heater":null,"torque_leak":null}
[muse] scenario 3: {"hypothesis":"Stuck heater in long eclipse drains battery below floor despite safe mode","orbit":{"beta_deg":0.0,"f0_deg":180.0},"rw_faults":[],"heater":{"onset_s":0.0,"power_W":6.0},"torque_leak":null}
[muse] scenario 4: {"hypothesis":"Combined leak heater and derate prevent safe recovery causing battery exhaustion","orbit":{"beta_deg":10.0,"f0_deg":90.0},"rw_faults":[{"wheel":2,"onset_s":500.0,"type":"torque_derate","severity":0.5}],"heater":{"onset_s":500.0,"power_W":3.0},"torque_leak":{"onset_s":500.0,"mag_Nm":8e-07,"axis":[1.0,0.0,0.0]}}
[muse] scenario 5: {"hypothesis":"Second faulty wheel not isolated by FDIR causes loss of control","orbit":{"beta_deg":40.0,"f0_deg":0.0},"rw_faults":[{"wheel":0,"onset_s":200.0,"type":"friction","severity":1.0},{"wheel":1,"onset_s":400.0,"type":"torque_derate","severity":0.8}],"heater":null,"torque_leak":{"onset_s":400.0,"mag_Nm":1e-06,"axis":[0.0,1.0,0.0]}}
[muse] scenario 6: {"hypothesis":"Late wheel failure after momentum buildup triggers saturation of survivors","orbit":{"beta_deg":70.0,"f0_deg":200.0},"rw_faults":[{"wheel":0,"onset_s":7000.0,"type":"torque_derate","severity":1.0}],"heater":null,"torque_leak":{"onset_s":0.0,"mag_Nm":1.2e-06,"axis":[1.0,0.0,0.0]}}
[muse] scenario 7: {"hypothesis":"Heater plus friction power blocks safe exit leading to battery floor","orbit":{"beta_deg":20.0,"f0_deg":270.0},"rw_faults":[{"wheel":2,"onset_s":1000.0,"type":"friction","severity":0.8}],"heater":{"onset_s":1000.0,"power_W":4.0},"torque_leak":null}
[sim] running 8 Basilisk sims (2 orbits = 11,354 s each, policy v1) on 4 workers ...
[sim] #1 ok  Dead wheel plus secular leak exceeds remaining momentum capacity
        margins: battery +0.200 SoC  att_err 2.28x bound  att_dur 0.01x limit  wheel 0.30x sat  sat_dur 0.00x  isolated -  final SAFE
[sim] #3 ok  Stuck heater in long eclipse drains battery below floor despite safe mode
        margins: battery +0.192 SoC  att_err 4.59x bound  att_dur 0.02x limit  wheel 1.00x sat  sat_dur 0.08x  isolated -  final SAFE
[sim] #2 ok  Moderate friction evades FDIR while wasting power and degrading pointing
        margins: battery +0.374 SoC  att_err 3.85x bound  att_dur 0.02x limit  wheel 1.04x sat  sat_dur 0.33x  isolated [0]  final SAFE
[sim] #0 VIOLATION attitude_loss  Two dead wheels leave underactuated control causing attitude loss
        margins: battery +0.376 SoC  att_err 4.05x bound  att_dur 7.80x limit  wheel 0.34x sat  sat_dur 0.00x  isolated [0]  final SAFE
        t=   100s  FAULT rw0 applied {"wheel": 0, "onset_s": 100.0, "type": "torque_derate", "severity": 1.0}
        t=   100s  FAULT rw1 applied {"wheel": 1, "onset_s": 100.0, "type": "torque_derate", "severity": 1.0}
        t=   125s  POLICY FDIR: wheel 0 isolated (residual 8.43e-04 Nm)
        t=   905s  POLICY -> SAFE (sun-point, payload off): attitude error 121.4 deg > 15.0 for 135s
[sim] #4 ok  Combined leak heater and derate prevent safe recovery causing battery exhaustion
        margins: battery +0.199 SoC  att_err 3.56x bound  att_dur 0.01x limit  wheel 0.89x sat  sat_dur 0.00x  isolated -  final NOMINAL
[sim] #5 ok  Second faulty wheel not isolated by FDIR causes loss of control
        margins: battery +0.200 SoC  att_err 2.89x bound  att_dur 0.01x limit  wheel 0.70x sat  sat_dur 0.00x  isolated [0]  final NOMINAL
[sim] #6 ok  Late wheel failure after momentum buildup triggers saturation of survivors
        margins: battery +0.200 SoC  att_err 2.96x bound  att_dur 0.01x limit  wheel 0.76x sat  sat_dur 0.00x  isolated [0]  final NOMINAL
[sim] #7 ok  Heater plus friction power blocks safe exit leading to battery floor
        margins: battery +0.115 SoC  att_err 4.19x bound  att_dur 0.02x limit  wheel 0.82x sat  sat_dur 0.00x  isolated [2]  final SAFE
[sim] 1/8 scenarios violated a safety constraint (9 s wall)
[log] {"ts_utc": "2026-11-04T06:11:02+00:00", "model": "muse-spark-1.3", "endpoint": "https://api.meta.ai/v1/chat/completions", "response_id": "chatcmpl-01a1a52f-425a-7634-8501-6fc98bfd5945", "request_id": "2b65af1a-3043-45d9-86d7-2c91da2bec0a", "latency_s": 37.53}
full record: data/live/live_2026-11-04T061102Z.json
(exit 0, 48 s)
```
