# Surgical causal replay: headline case a6e8087b7a52c977

**Question.** Is the attitude loss caused by the FDIR *wheel-isolation decision*, or by the policy as a whole
(safe-mode switching, sun-pointing, payload shedding)?

**Method.** Same faults, same orbit, fixed (consecutive) wheel_saturation rule, three arms:

- **full**: v1 policy as used in every experiment.
- **isolation-only suppressed** (`no_isolate`): v1 policy with a single change, `suppress_isolation=True`. The residual
  detector still runs and logs "wheel i would be isolated ... SUPPRESSED". It never removes a wheel (isolation and
  swap are both suppressed). Safe-mode entry/exit, sun-pointing, payload shedding and SoC logic are unchanged
  (`src/ff_sim.py`, FDIR branch).
- **policy off**: policy disabled (no FDIR, no safe mode).

Reproduce (keyless, about 1 min): `make causal` (= `python3 src/causal_replay.py`). Add `--sweep` for the neighbourhood
sweep and `--params FILE.json` for any other case. Raw output: `data/satfix/causal_replay.json`, `data/satfix/causal_sweep.json`.
Telemetry is sampled every 10 s and attitude metrics count only after the 900 s grace period.

## Result

**Minimized case (the demo case: rw0 friction 0.2 at 105 s, rw1 torque derate 1.0 at 505 s, beta 65, f0 255).**
Suppressing *only* the isolation action removes the violation, so in this case the isolation decision is the cause.

| | full policy | isolation-only suppressed | policy off |
|---|---|---|---|
| violations | attitude_loss @ 2915 s | none | none |
| peak attitude error after grace | 179.9 deg | 136.9 deg | 16.2 deg |
| time with attitude error > 30 deg | 9790 s | 220 s | 0 s |
| longest continuous > 30 deg (limit 1200 s) | 9645 s | 30 s | 0 s |
| min SoC (floor 0.20) | 0.650 | 0.650 | 0.378 |
| peak wheel speed / sat threshold | 1.036 | 1.021 | 0.340 |
| longest consecutive wheel saturation (limit 60 s) | 5 s | 15 s | 0 s |
| time in SAFE | 10310 s | 3420 s | 0 s |
| final mode | SAFE | SAFE | NOMINAL |
| isolated wheels at end | [0] | [] | [] |

Causal trace (full policy): t=105 s mild friction on rw0 -> t=120 s FDIR isolates rw0 (residual 3.99e-4 Nm, just
above the 3e-4 Nm threshold), which uses up its only isolation (min_avail=3) -> t=505 s rw1 dies (derate 1.0). FDIR
detects it but cannot isolate it, so the controller keeps allocating torque to a dead wheel and is left with 2
working wheels -> the attitude error diverges -> SAFE at 930 s (138 deg) -> back to NOMINAL at 1530 s -> SAFE again at 1650 s
and it never recovers (179.9 deg peak, >30 deg for 9645 s straight). With isolation suppressed, rw0 (mild friction) stays in the loop, and
the craft cycles SAFE/NOMINAL with 15-65 deg excursions that never stay above 30 deg for more than 30 s.

Note that "isolation-only suppressed" is still *worse* than "policy off" on attitude (137 vs 16 deg peak), while it is better on SoC.
The safe-mode/sun-pointing logic also has a cost here, but it does not cross a constraint. Only the isolation decision does.

**Original search hit (muse_seed1 run 173, rw0 friction severity 1.0 instead of 0.2).** full: attitude_loss;
isolation suppressed: clean (peak 140.6 deg, longest > 30 deg run 135 s); policy off: **also attitude_loss**
(@3015 s, peak 65.8 deg, 2620 s continuous). Honest reading: the *original* run is not purely policy-induced, because a
fully dead-friction wheel plus a dead wheel fails without the policy too. The minimizer reduced the friction to 0.2,
which turned it into a clean policy-induced counterexample. With the original severity, suppressing isolation alone still avoids the violation.

## Robustness: neighbourhood sweep (24 cases)

rw0 friction severity {0.15, 0.2, 0.3, 0.5} x rw1 derate onset {305, 505, 1005} s x beta {45, 65} deg (f0 255):

| arm | cases with a violation |
|---|---|
| full policy | **24/24** (all attitude_loss) |
| isolation-only suppressed | **0/24** |
| policy off | 6/24 (only severity 0.5, where the friction itself is heavy) |

So the effect is not a knife-edge. Across this neighbourhood, removing the isolation action alone removes every failure,
and for severity <= 0.3 the failure exists only because of the policy.

## Full metric tables and policy logs (generated)

### a6e8087b7a52c977 minimized (demo case)

| metric | full policy | isolation-only suppressed | policy off |
|---|---|---|---|
| violations | `{"attitude_loss": 2915.0}` | `{}` | `{}` |
| peak_att_err_after_grace_deg | `179.9` | `136.9` | `16.2` |
| time_att_err_gt_30deg_s | `9790.0` | `220.0` | `0.0` |
| longest_att_err_gt_30deg_run_s | `9645` | `30` | `0` |
| min_soc | `0.65` | `0.65` | `0.378` |
| peak_wheel_speed_frac_of_sat_threshold | `1.03619` | `1.02111` | `0.34027` |
| longest_consecutive_wheel_sat_s | `5` | `15` | `0` |
| time_in_safe_mode_s | `10310.0` | `3420.0` | `0.0` |
| final_mode | `"SAFE"` | `"SAFE"` | `"NOMINAL"` |
| isolated_wheels_at_end | `[0]` | `[]` | `[]` |
| policy_actions | `4` | `14` | `0` |

Policy log (full):
    t=   120s  POLICY FDIR: wheel 0 isolated (residual 3.99e-04 Nm)
    t=   930s  POLICY -> SAFE (sun-point, payload off): attitude error 138.2 deg > 15.0 for 120s
    t=  1530s  POLICY -> NOMINAL (SoC 0.80)
    t=  1650s  POLICY -> SAFE (sun-point, payload off): attitude error 51.5 deg > 15.0 for 120s

Policy log (no_isolate):
    t=   120s  POLICY FDIR: wheel 0 would be isolated (residual 3.99e-04 Nm) - SUPPRESSED
    t=   530s  POLICY FDIR: wheel 1 would be isolated (residual 5.45e-04 Nm) - SUPPRESSED
    t=   905s  POLICY -> SAFE (sun-point, payload off): attitude error 15.1 deg > 15.0 for 270s
    t=  1505s  POLICY -> NOMINAL (SoC 0.82)
    t=  2745s  POLICY -> SAFE (sun-point, payload off): attitude error 15.9 deg > 15.0 for 120s
    t=  3345s  POLICY -> NOMINAL (SoC 0.71)
    t=  3590s  POLICY -> SAFE (sun-point, payload off): attitude error 15.4 deg > 15.0 for 120s
    t=  3610s  POLICY FDIR: wheel 3 would be isolated (residual 3.16e-04 Nm) - SUPPRESSED
    t=  4190s  POLICY -> NOMINAL (SoC 0.82)
    t=  5270s  POLICY -> SAFE (sun-point, payload off): attitude error 16.0 deg > 15.0 for 120s
    t=  5870s  POLICY -> NOMINAL (SoC 0.93)
    t=  6080s  POLICY -> SAFE (sun-point, payload off): attitude error 16.0 deg > 15.0 for 120s
    t=  6680s  POLICY -> NOMINAL (SoC 1.00)
    t= 10935s  POLICY -> SAFE (sun-point, payload off): attitude error 16.1 deg > 15.0 for 120s

### muse_seed1 run 173 (original search hit)

| metric | full policy | isolation-only suppressed | policy off |
|---|---|---|---|
| violations | `{"attitude_loss": 2915.0}` | `{}` | `{"attitude_loss": 3015.0}` |
| peak_att_err_after_grace_deg | `179.9` | `140.6` | `65.8` |
| time_att_err_gt_30deg_s | `9790.0` | `1970.0` | `9820.0` |
| longest_att_err_gt_30deg_run_s | `9645` | `135` | `2620` |
| min_soc | `0.65` | `0.65` | `0.595` |
| peak_wheel_speed_frac_of_sat_threshold | `1.03619` | `0.71575` | `0.31031` |
| longest_consecutive_wheel_sat_s | `5` | `0` | `0` |
| time_in_safe_mode_s | `10310.0` | `7910.0` | `0.0` |
| final_mode | `"SAFE"` | `"SAFE"` | `"NOMINAL"` |
| isolated_wheels_at_end | `[0]` | `[]` | `[]` |
| policy_actions | `4` | `29` | `0` |

Policy log (full):
    t=   120s  POLICY FDIR: wheel 0 isolated (residual 3.98e-04 Nm)
    t=   930s  POLICY -> SAFE (sun-point, payload off): attitude error 138.2 deg > 15.0 for 120s
    t=  1530s  POLICY -> NOMINAL (SoC 0.80)
    t=  1650s  POLICY -> SAFE (sun-point, payload off): attitude error 51.5 deg > 15.0 for 120s

Policy log (no_isolate):
    t=   120s  POLICY FDIR: wheel 0 would be isolated (residual 3.98e-04 Nm) - SUPPRESSED
    t=   530s  POLICY FDIR: wheel 1 would be isolated (residual 5.49e-04 Nm) - SUPPRESSED
    t=   905s  POLICY -> SAFE (sun-point, payload off): attitude error 60.6 deg > 15.0 for 365s
    t=  1505s  POLICY -> NOMINAL (SoC 0.85)
    t=  1625s  POLICY -> SAFE (sun-point, payload off): attitude error 43.2 deg > 15.0 for 120s
    t=  2225s  POLICY -> NOMINAL (SoC 0.99)
    t=  2435s  POLICY -> SAFE (sun-point, payload off): attitude error 63.2 deg > 15.0 for 120s
    t=  3035s  POLICY -> NOMINAL (SoC 0.99)
    t=  3210s  POLICY -> SAFE (sun-point, payload off): attitude error 64.1 deg > 15.0 for 120s
    t=  3810s  POLICY -> NOMINAL (SoC 1.00)
    t=  3965s  POLICY -> SAFE (sun-point, payload off): attitude error 58.7 deg > 15.0 for 120s
    t=  4565s  POLICY -> NOMINAL (SoC 1.00)
    t=  4825s  POLICY -> SAFE (sun-point, payload off): attitude error 57.3 deg > 15.0 for 120s
    t=  5425s  POLICY -> NOMINAL (SoC 1.00)
    t=  5605s  POLICY -> SAFE (sun-point, payload off): attitude error 65.4 deg > 15.0 for 120s
    t=  6205s  POLICY -> NOMINAL (SoC 1.00)
    t=  6325s  POLICY -> SAFE (sun-point, payload off): attitude error 63.8 deg > 15.0 for 120s
    t=  6925s  POLICY -> NOMINAL (SoC 1.00)
    t=  7045s  POLICY -> SAFE (sun-point, payload off): attitude error 59.0 deg > 15.0 for 120s
    t=  7645s  POLICY -> NOMINAL (SoC 1.00)
    t=  7905s  POLICY -> SAFE (sun-point, payload off): attitude error 59.5 deg > 15.0 for 120s
    t=  8505s  POLICY -> NOMINAL (SoC 0.99)
    t=  8690s  POLICY -> SAFE (sun-point, payload off): attitude error 65.9 deg > 15.0 for 120s
    t=  9290s  POLICY -> NOMINAL (SoC 0.98)
    t=  9465s  POLICY -> SAFE (sun-point, payload off): attitude error 62.1 deg > 15.0 for 120s
    t= 10065s  POLICY -> NOMINAL (SoC 1.00)
    t= 10525s  POLICY -> SAFE (sun-point, payload off): attitude error 55.9 deg > 15.0 for 120s
    t= 11125s  POLICY -> NOMINAL (SoC 1.00)
    t= 11245s  POLICY -> SAFE (sun-point, payload off): attitude error 64.7 deg > 15.0 for 120s

