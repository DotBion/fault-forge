# Root-cause defects in the v1 FDIR policy (by mechanism)

**Input.** All 276 in-scope, policy-induced, reproducing minimized counterexamples in `data/cmp/minimized.jsonl`
after the saturation fix (consecutive rule; legacy-rule cache entries re-minimized first). "Policy-induced" = the
minimized target violation does not occur with the policy off.

**Method.** `make defects` (= `python3 src/defects.py`, about 10 min with `DEFECTS_ARGS="--workers 4"`) re-runs each case
under five single-change arms and classifies it by which ablation removes the target violation:

| arm | change vs v1 |
|---|---|
| full | none |
| no_isolate | FDIR detects but never removes a wheel (`suppress_isolation=True`) |
| swap | v3 rule: re-enable the isolated wheel if a later one has a > 1.5-2x larger residual (`isolation_swap=True`) |
| no_safe | safe-mode triggers disabled (`att_safe_deg=1e9`, `soc_shed=-1`) |
| off | policy disabled |

Raw results: `data/satfix/defects.json` (per case: minimized params, every arm's violations, isolated wheels, peak
attitude error, min SoC, policy/fault log). Replay any case and arm: `python3 src/defects.py --replay KEYPREFIX ARM`.

| defect | cases | share | removing the cause fixes the target |
|---|---|---|---|
| D1 isolation lock-in | 254 | 92 % | no_isolate 254/254, swap 253/254 |
| D2 isolation removes a wheel that is still needed | 19 | 7 % | no_isolate 19/19 (fully clean 10/19) |
| D3 safe-mode chattering / safe-mode induced | 3 | 1 % | no_safe 3/3, no_isolate 0/3 |
| neither ablation alone | 0 | 0 % | |

Cross-cutting code defect (shows up inside D1 and D2): **in 63 of 276 cases, two wheels crossed the persistence
threshold in the same 5 s chunk and FDIR isolated the lower-index one, even though the other had a larger residual.**
The FDIR loop in `src/ff_sim.py` walks wheels in index order and gives the one allowed isolation to the first wheel
that qualifies. It never compares residuals (59 D1 cases, 4 D2 cases).

---

## D1: isolation lock-in (one-shot isolation spent on the milder fault), 254 cases

**Mechanism.** FDIR may isolate only while > 3 wheels are available (`min_avail=3`). The first wheel whose torque
residual stays above `max(0.25*|u|, 3e-4 Nm)` for 3 chunks is isolated. A mild fault (friction around 0.2 gives a
residual just above 3e-4 Nm) uses that single isolation. When a second, worse fault arrives, FDIR detects it but
cannot act, so the controller keeps allocating torque to a dead or heavily degraded wheel while the healthy-but-mild
wheel sits isolated. The policy never re-arbitrates. 220 cases are two friction faults, 33 friction + derate.

**Causal trace (headline case `a6e8087b7a52c977`: rw0 friction 0.2 @105 s, rw1 derate 1.0 @505 s, beta 65).**

```
full:        t=105 FAULT rw0 friction 0.2
             t=120 FDIR: wheel 0 isolated (residual 3.99e-04 Nm)     <- one isolation used on the mild wheel
             t=505 FAULT rw1 derate 1.0                               <- dead wheel, cannot be isolated (3 left)
             t=930 SAFE (att err 138 deg) ... 1530 NOMINAL ... 1650 SAFE, never recovers
             -> attitude_loss @2915 s, peak 179.9 deg, final SAFE, isolated [0]
no_isolate:  same detections, both SUPPRESSED -> no violation (peak 136.9 deg, longest > 30 deg run 30 s)
swap:        t=530 FDIR: swap - wheel 0 re-enabled, wheel 1 isolated (9.70e-04 > 2 x 3.99e-04) -> no violation
off:         no violation, peak 16.2 deg
```

Replay: `make causal` (full table + 24-case neighbourhood sweep: full 24/24 violate, no_isolate 0/24; see
`causal_replay.md`), or `python3 src/defects.py --replay a6e8087b full` (and `... swap`, `... no_isolate`).
Second exemplar with no leak or heater: `python3 src/defects.py --replay 03bd47a6 full` (rw1 friction 0.2 @0 s, rw2
friction 0.7 @50 s: full isolates rw1, peak 166.8 deg; swap isolates rw2, peak 9.6 deg).

**Fix direction and caveat.** The swap rule fixes 253/254 *minimized* cases. On full stored runs, however, v3 (swap)
breaks 169 clean runs and fixes 125 (README, repair section), so swap alone is not a safe fix. A residual-ranked,
re-arbitrating isolation needs the full regression gate.

## D2: isolation removes a wheel that is still needed, 19 cases

**Mechanism.** Isolation is correct as detection but wrong as an action. There are two variants:

- *Degraded but still useful wheel isolated under an external torque leak (13 cases).* A mild fault (friction 0.2 or
  derate 0.8-0.9) on the wheel that carries the leak's momentum trips the detector (anywhere from 15 s to 7300 s
  into the run). Removing it leaves 3 wheels with less momentum capacity on the leak axis. 8 cases end in
  attitude loss; in all 8, a wheel also saturates with the policy off, so only the attitude loss is
  policy-induced. 5 cases end in saturation (3 of these fail battery_floor with the policy off).
- *Healthy wheel isolated (6 cases).* The detector flags a wheel with no injected fault during a large slew (a
  SAFE->NOMINAL re-slew or a dead-wheel transient). In 4 of the 6, the faulty wheel crossed in the same chunk with a
  larger residual and lost the index-order tie-break. We have not traced why the healthy wheel shows a residual
  (likely torque command vs delivered mismatch during the slew).

**Causal trace (healthy-wheel variant, `b8aa55fd`: heater 5.2 W @3000 s, rw1 derate 1.0 @3500 s, beta 0).**

```
full:        t=3510 SAFE (SoC 0.40) ... t=5285 NOMINAL (SoC 0.70)
             t=5300 FDIR: wheel 0 isolated (residual 1.09e-03 Nm)     <- wheel 0 has no fault
             (same chunk: dead wheel 1 residual 2.20e-03 Nm, cannot be isolated any more)
             t=5715 SAFE (att err 164 deg) -> attitude_loss @6805 s, peak 176.5 deg, isolated [0]
no_isolate:  t=5300 wheel 0 would be isolated (1.09e-03) SUPPRESSED; wheel 1 would be isolated (2.20e-03) SUPPRESSED
             -> no violation, final NOMINAL
```

Replay: `python3 src/defects.py --replay b8aa55fd full` / `... no_isolate`. Leak variant:
`python3 src/defects.py --replay 505563eb full` (rw2 friction 0.2 + 1.2 uNm +Z leak @400 s: rw2 isolated at 6385 s
-> SAFE/NOMINAL cycling -> attitude_loss @9265 s; with no_isolate or off the leak still saturates a wheel, but attitude holds).

## D3: safe-mode chattering drives a wheel into saturation, 3 cases (2 clear, 1 SoC-triggered)

**Mechanism.** The SAFE trigger (attitude error > 15 deg for 120 s) and the NOMINAL return (SoC > 70 % after
>= 600 s) have no hysteresis on attitude. On a 3-wheel craft carrying a leak, attitude hovers around 15-19 deg in
NOMINAL. The policy therefore toggles SAFE <-> NOMINAL about every 13 min (13 and 10 SAFE entries in the two clear cases), and each sun-point/nadir re-slew pumps momentum
into the remaining wheels until one stays at >= 98 % for > 60 s. Without safe mode the craft holds about 17 deg and
never saturates. Isolation is not the cause here (no_isolate still saturates). The third case (`b297ea92`, heater +
leak + mild friction) has only 2 SAFE entries, both SoC-triggered; there SAFE's sun-pointing attitude saturates a
wheel, and with the policy off the battery fails instead.

**Causal trace (`8a5158f3`: rw1 derate 1.0 + rw3 friction 0.35 + 1.0 uNm +X leak, all @100 s, beta 12).**

```
full:        t=125 FDIR: wheel 1 isolated (correct: the dead wheel)
             t=905 SAFE (16.2 deg > 15) -> 1505 NOMINAL -> 1625 SAFE (15.9) -> 2225 NOMINAL -> ... 13 SAFE entries,
             each at 15.3-19.7 deg -> wheel_saturation @10660 s
no_safe:     t=125 wheel 1 isolated, no mode switches -> no violation, peak 17.1 deg
off:         attitude_loss (the dead wheel is never isolated), so the saturation target is policy-induced, but the
             case is not clean without a policy
```

Replay: `python3 src/defects.py --replay 8a5158f3 full` / `... no_safe`.
