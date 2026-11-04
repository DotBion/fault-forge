# Waivers: previously clean runs broken by budget-mode accepted patches

Budget gate allows at most 3 previously clean runs (0.1% of the 3,508-run suite) per accepted patch.

## b1t1: change `{"wheel_safe_frac": 0.97, "wheel_safe_s": 60.0}`  (accepted (budget): 26 fixes, 2 runs with new violations (1 previously clean = waived), net +24 on all 3508 runs)
- **museblind_seed1_28** [leak+rw2_torque_derate+rw3_torque_derate] -> {'wheel_saturation': 9290.0}  (file `data/gated/waivers/b1t1_museblind_seed1_28.jsonl`)
  - with patch: `python3 src/replay.py data/gated/waivers/b1t1_museblind_seed1_28.jsonl 0 --policy data/gated/policy_b1t1.json`
  - before patch: `python3 src/replay.py data/gated/waivers/b1t1_museblind_seed1_28.jsonl 0 --policy v1`

