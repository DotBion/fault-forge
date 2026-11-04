# Rejected proposals (strict gate unless noted)

Gate: strict = 0 new (run, violation) pairs vs the current policy and fixes > 0 on the full 3,508-run suite; evaluation stops early once a few new violations are found (counts are then partial). Budget = net fixes > 0 and <= 3 previously clean runs broken.

| id | phase | base | change | new violations (prev. clean runs) | fixes | runs evaluated | why rejected |
|---|---|---|---|---|---|---|---|
| b2t1 | budget | b1t1 | `{"fdir_hard_Nm": 0.0005}` | 4 (4) | 3 | 797 (early stop) | rejected (budget): 4 previously clean runs broken (max 3), 4 runs with new violations, 3 fixes, net -1, 797 runs evaluated (stopped early) |
| b2t2 | budget | b1t1 | `{"isolation_swap": true, "swap_ratio": 3.0, "swap_max_iso_res_Nm": 0.0005}` | 4 (4) | 2 | 659 (early stop) | rejected (budget): 4 previously clean runs broken (max 3), 4 runs with new violations, 2 fixes, net -2, 659 runs evaluated (stopped early) |
| r1t1 | strict (param) | v1 | `{"isolation_swap": true, "swap_ratio": 2.0}` | 20 (20) | 36 | 861 (early stop) | rejected (strict): 20 new violations in 20 runs (20 previously clean), 36 fixes, evaluation stopped early after 861 runs |
| r1t2 | strict (param) | v1 | `{"fdir_abs_Nm": 0.0006}` | 14 (11) | 39 | 1777 (early stop) | rejected (strict): 14 new violations in 14 runs (11 previously clean), 39 fixes, evaluation stopped early after 1777 runs |
| r1t3 | strict (param) | v1 | `{"resume_min_s": 900.0}` | 17 (10) | 10 | 3508 | rejected (strict): 17 new violations in 16 runs (10 previously clean) vs 10 fixes on the full suite |
| r1t4 | strict (param) | v1 | `{"att_safe_deg": 18.0}` | 4 (3) | 3 | 982 (early stop) | rejected (strict): 4 new violations in 3 runs (3 previously clean), 3 fixes, evaluation stopped early after 982 runs |
| r1t5 | strict (param) | v1 | `{"isolation_swap": true, "swap_ratio": 2.5, "swap_min_res_Nm": 0.001, "swap_max_iso_res_Nm": 0.0006}` | 3 (3) | 0 | 7 (early stop) | rejected (strict): 3 new violations in 3 runs (3 previously clean), 0 fixes, evaluation stopped early after 7 runs |
| r1t6 | strict (param) | v1 | `{"isolation_swap": true, "swap_ratio": 5.0, "swap_min_res_Nm": 0.002, "swap_max_iso_res_Nm": 0.0004}` | 3 (3) | 0 | 25 (early stop) | rejected (strict): 3 new violations in 3 runs (3 previously clean), 0 fixes, evaluation stopped early after 25 runs |
| r2t1 | strict (param) | v1 | `{"isolation_swap": true, "swap_ratio": 2.0, "swap_min_res_Nm": 0.0008, "swap_max_iso_res_Nm": 0.0006}` | 3 (3) | 0 | 66 (early stop) | rejected (strict): 3 new violations in 3 runs (3 previously clean), 0 fixes, evaluation stopped early after 66 runs |
| r2t2 | strict (param) | v1 | `{"wheel_safe_frac": 0.97, "wheel_safe_s": 60.0}` | 2 (1) | 26 | 3508 | rejected (strict): 2 new violations in 2 runs (1 previously clean) vs 26 fixes on the full suite |
| r2t3 | strict (param) | v1 | `{"wheel_safe_frac": 0.97, "wheel_safe_s": 120.0}` | 2 (0) | 9 | 3508 | rejected (strict): 2 new violations in 2 runs (0 previously clean) vs 9 fixes on the full suite |
| r2t4 | strict (param) | v1 | `{"fdir_persist": 4}` | 3 (3) | 0 | 13 (early stop) | rejected (strict): 3 new violations in 3 runs (3 previously clean), 0 fixes, evaluation stopped early after 13 runs |
| s1 | structural | v1 | `{"fdir_readmit_s": 1800.0}` | 3 (3) | 1 | 663 (early stop) | rejected (strict): 3 new violations in 3 runs (3 previously clean), 1 fixes, evaluation stopped early after 663 runs |
| s2 | structural | v1 | `{"fdir_hard_Nm": 0.0005}` | 3 (3) | 3 | 794 (early stop) | rejected (strict): 3 new violations in 3 runs (3 previously clean), 3 fixes, evaluation stopped early after 794 runs |

First regressed runs per reject (replay: `python3 src/gated_v2.py replay <suite id> --policy <id>`):

- b2t1: cmaes_seed0_176 [heater+rw1_friction+rw2_friction], cmaes_seed0_293 [rw0_friction+rw2_friction], cmaes_seed0_294 [rw0_friction+rw2_friction], cmaes_seed0_297 [heater+rw0_friction+rw2_friction]
- b2t2: cmaes_seed0_169 [heater+rw1_friction+rw2_friction], cmaes_seed0_176 [heater+rw1_friction+rw2_friction], cmaes_seed0_294 [rw0_friction+rw2_friction], cmaes_seed0_297 [heater+rw0_friction+rw2_friction]
- r1t1: cmaes_seed0_109 [heater+leak+rw1_friction+rw2_friction], cmaes_seed0_120 [heater+leak+rw2_friction+rw3_torque_derate], cmaes_seed0_136 [heater+leak+rw2_friction+rw3_torque_derate], cmaes_seed0_137 [heater+leak+rw1_friction+rw2_friction], cmaes_seed0_150 [rw1_friction+rw3_torque_derate], cmaes_seed0_158 [heater+rw1_friction+rw2_friction]
- r1t2: cmaes_seed0_137 [heater+leak+rw1_friction+rw2_friction], cmaes_seed0_169 [heater+rw1_friction+rw2_friction], cmaes_seed0_257 [heater+rw0_friction+rw2_friction], cmaes_seed0_293 [rw0_friction+rw2_friction], cmaes_seed0_294 [rw0_friction+rw2_friction], cmaes_seed0_297 [heater+rw0_friction+rw2_friction]
- r1t3: cmaes_seed0_120 [heater+leak+rw2_friction+rw3_torque_derate], cmaes_seed0_240 [leak+rw0_friction+rw2_friction], cmaes_seed0_277 [heater+rw0_friction+rw2_friction], cmaes_seed0_279 [rw0_friction+rw2_friction], muse_seed0_150 [leak+rw1_friction+rw2_friction], muse_seed0_182 [leak+rw0_friction+rw2_friction]
- r1t4: cmaes_seed0_120 [heater+leak+rw2_friction+rw3_torque_derate], cmaes_seed0_160 [heater+rw1_friction+rw2_friction], muse_seed0_204 [heater+leak+rw1_torque_derate+rw2_torque_derate]
- r1t5: cmaes_seed0_137 [heater+leak+rw1_friction+rw2_friction], cmaes_seed0_150 [rw1_friction+rw3_torque_derate], cmaes_seed0_169 [heater+rw1_friction+rw2_friction]
- r1t6: cmaes_seed0_278 [heater+rw1_friction+rw2_friction], cmaes_seed0_294 [rw0_friction+rw2_friction], cmaes_seed2_117 [leak+rw0_friction+rw2_friction]
- r2t1: cmaes_seed0_137 [heater+leak+rw1_friction+rw2_friction], cmaes_seed0_150 [rw1_friction+rw3_torque_derate], cmaes_seed0_158 [heater+rw1_friction+rw2_friction]
- r2t2: museblind_seed1_121 [heater+leak+rw1_torque_derate+rw2_torque_derate], museblind_seed1_28 [leak+rw2_torque_derate+rw3_torque_derate]
- r2t3: museblind_seed1_115 [leak+rw1_torque_derate], museblind_seed1_121 [heater+leak+rw1_torque_derate+rw2_torque_derate]
- r2t4: cmaes_seed0_137 [heater+leak+rw1_friction+rw2_friction], cmaes_seed0_176 [heater+rw1_friction+rw2_friction], cmaes_seed0_294 [rw0_friction+rw2_friction]
- s1: cmaes_seed0_158 [heater+rw1_friction+rw2_friction], cmaes_seed0_169 [heater+rw1_friction+rw2_friction], cmaes_seed0_176 [heater+rw1_friction+rw2_friction]
- s2: cmaes_seed0_176 [heater+rw1_friction+rw2_friction], cmaes_seed0_293 [rw0_friction+rw2_friction], cmaes_seed0_294 [rw0_friction+rw2_friction]
