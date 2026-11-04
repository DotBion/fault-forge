# Real-world references for the FaultForge reaction-wheel FDIR / safe-mode policy

Purpose: answer the "strawman policy" objection. The policy under test (`src/ff_sim.py`, `POLICY`, "v1") was
written by us for this project. Below are published sources for each of its design choices, followed by an honest
comparison. Every URL was fetched on 2026-11-03 (HTTP 200, content checked).

## What our v1 policy does (from `src/ff_sim.py`)

| Rule | v1 value |
|---|---|
| Wheel FDIR residual | per wheel, \|commanded torque - delivered torque (J_s * dOmega/dt)\| |
| Trip threshold | residual > max(0.25 x \|commanded\|, **3e-4 Nm**) for 3 consecutive 5 s checks (15 s persistence) |
| Isolation | remove the wheel from torque allocation (`rwMotorTorque` availability). **At most one isolation**: never go below 3 available wheels (`min_avail = 3`) |
| Wheels | 4 x BCT RWP015 (4 mNm max torque, 15 mNms), 3 orthogonal + 1 skew |
| Safe-mode entry | attitude error > **15 deg for 120 s** -> sun-safe point, payload off; also battery SoC < 0.40 |
| Safety constraint (what counts as a failure) | attitude error > **30 deg for more than 1200 s** (after a 900 s grace), battery floor, wheel saturation > 60 s |

## Sources

1. **Model-based FDIR for CubeSats (EUCASS 2019)** - *Design of a Model-Based Failure Detection Isolation and
   Recovery System for Cubesats*, DOI 10.13009/EUCASS2019-702.
   https://www.eucass.eu/doi/EUCASS2019-0702.pdf
   - 4 reaction wheels in a pyramid. Wheel residual r = T_rw - T_c, where T_rw = -I_rw * d(omega_rw)/dt from the
     tachometer and T_c is the commanded torque. Detection is a **threshold on the moving RMS of that residual**.
     Accommodation **removes the faulty wheel from the configuration matrix** and redesigns the controller gains.
   - States explicitly: "this configuration can only deal with one faulty reaction wheel because two faulty
     reaction wheels lead to an unfeasible allocation problem."
   - **Match:** this is the same residual definition, the same isolation action, and the same one-isolation limit
     as ours. Ours uses a persistence count where they use a moving RMS. The paper gives no numeric threshold.

2. **NASA Software Engineering Handbook, 9.07 Fault Detection and Response** (fault-protection principles collected
   from GSFC and JPL).
   https://swehb.nasa.gov/spaces/SWEHBVC/pages/85426326/9.07+Fault+Detection+and+Response
   - 4.9.1.3 *Protection for multiple faults*: "Fault protection shall handle multiple, **non-coincident** faults,
     provided that they occur in functionally independent system elements." It also adds that a latent fault
     exposed by a recovery action is not a concurrent fault.
   - 3.7.4.5 *Fault indication filtering*: use trigger and persistence values that are not "hair triggered".
   - **Match:** our headline cases are exactly this class: two faults on different wheels, hundreds of seconds
     apart. Our persistence counter follows 3.7.4.5. This is the strongest argument that the cases FaultForge
     finds are in scope for real fault protection, not exotic.

3. **Aerospace Corp. TOR-2009(8591)-14, *Effective Fault Management Guidelines***.
   https://aerospace.org/sites/default/files/maiw/TOR-2009(8591)-14.pdf
   - Uses "a reaction wheel friction torque increasing due to bearing failure" as the example fault. The canonical
     fault-protection response is to switch out the failed unit, e.g. "turning off the suspect reaction wheel".
     It defines safe mode as a power- and thermal-positive actively controlled survival mode, and lists sun-point
     as a contingency mode.
   - **Match:** our fault types (friction increase, torque derate), our response (isolate the suspect wheel), and
     our safe mode (sun-safe point, payload off) all follow this guideline's pattern. It gives no CubeSat-specific
     thresholds.

4. **ECSS-E-ST-60-30C, *Satellite AOCS requirements*** (ESA/ECSS standard, 30 Aug 2013).
   https://ecss.nl/wp-content/uploads/standards/ecss-e/ECSS-E-ST-60-30C30August2013.pdf
   - 5.1.1.8: on a major anomaly the AOCS shall autonomously reach and control a safe pointing attitude. The FDIR
     clause lists "a local hardware reconfiguration replacing a faulty unit... without any change of AOCS mode" and
     "a reconfiguration of several units and a switch to another mode, including safe mode". It notes that whether
     to stay in mode or go straight to safe mode after a failure is a design trade-off.
   - **Match:** this is the same two-tier structure we use (isolate the wheel and keep pointing, then escalate to
     safe mode on attitude error). The standard deliberately sets no numeric thresholds.

5. **Carrara et al., ISSFD 2014, CubeSat attitude operating modes (CONASAT/INPE)**.
   https://www.issfd.org/ISSFD_2014/ISSFD24_Paper_S1-4_carrara.pdf
   - A CubeSat with nominal, safe, and acquisition modes. Safe/acquisition pointing requirement: **error under 10
     deg** in roll, pitch, and yaw. Their wheels are much smaller (0.625 mNm max torque).
   - **Match:** this is a published CubeSat attitude-error figure of the same order as ours. Note that it is a
     *pointing requirement* inside safe mode, not a safe-mode *entry trigger*.

6. **Blue Canyon Technologies reaction wheel datasheet (RWp015)**, the wheel model Basilisk's `simIncludeRW`
   `BCT_RWP015` is based on.
   https://www.bluecanyontech.com/wp-content/uploads/Reaction-Wheels-Full-Product-Line.pdf
   - RWp015: 0.015 Nms max momentum, **0.004 Nm max torque**, flight-proven on CubeSats.
   - **Match:** this anchors the scale of our threshold. 3e-4 Nm is **7.5% of the wheel's max torque**.

Also checked: NASA F Prime's `Svc.Health` and the fault-protection component discussions
(https://github.com/nasa/fprime/discussions/2536). F Prime provides generic fault monitors with persistence counts
and response mapping. It ships **no reaction-wheel FDIR or attitude safe-mode thresholds**, so it supports the
persistence-filter pattern only. We found no public cFS app with reaction-wheel isolation thresholds.

## Honest verdict

- **Structure: strong match.** Residual = commanded vs. delivered wheel torque. Threshold plus persistence filter.
  Isolate by removing the wheel from allocation. At most one isolation on a 4-wheel set, so 3-axis control is kept.
  Escalate to sun-safe on attitude error. Each of these is documented (sources 1-4). The one-isolation rule is not
  arbitrary: source 1 states that the 4-wheel set can only tolerate one failed wheel.
- **Numbers: our choice, not taken from a reference.** No source we found publishes a numeric reaction-wheel
  residual threshold or a CubeSat safe-mode-entry attitude threshold. Real missions keep these values
  mission-specific, and the NASA handbook and ECSS standard say so. Our values are:
  - **3e-4 Nm**, 7.5% of RWp015 max torque, chosen so the policy passes 568/576 single-fault and nominal runs.
  - **15 deg / 120 s** to enter safe mode.
  - **30 deg / 1200 s** as the failure criterion.
  These are plausible, but **we cannot claim they are flight values**. Carrara et al. (10 deg) is the only
  published attitude number, and it is a pointing requirement, not a trigger.
- **The policy-induced failures depend on the structure, not on our threshold value.** In the headline case the
  policy spends its one isolation on a mild-friction wheel before a hard failure arrives. Any detector sensitive
  enough to catch a 20% friction rise will do that. Raising the threshold (repair v2, 6e-4 Nm) only moves the
  boundary, and the fresh search finds new cases against it.
- **Suggested on-screen line:** "Policy structure follows published CubeSat FDIR (EUCASS 2019; NASA SWEHB 9.07;
  ECSS-E-ST-60-30C). Thresholds are ours, tuned to pass 568/576 single-fault runs."
