"""FaultForge feasibility harness: 6U CubeSat with 4 reaction wheels + power system in Basilisk,
parameterized fault injection, a rule-based safe-mode policy, and explicit safety constraints.

Physics that is Basilisk (bsk 2.12.1): rigid-body + RW dynamics (reactionWheelStateEffector, incl.
torque/speed saturation and Coulomb/viscous friction), two-body orbit, gravity-gradient torque,
eclipse (cylindrical/conical shadow via `eclipse`), body-fixed solar panel (`simpleSolarPanel`,
cosine law on the true attitude), battery (`simpleBattery`), loads (`simplePowerSink`,
`ReactionWheelPower`). FSW: hillPoint/attTrackingError (nominal nadir), sunSafePoint (safe),
mrpFeedback + rwMotorTorque with RW availability.

Python-side (between 5 s sim chunks): fault onset (mutating the live RW config / sinks / external
torque), the recovery policy, and constraint checking.

    from ff_sim import run_scenario, default_params
    res = run_scenario(default_params())
"""
import copy
import json
import math
import time

import numpy as np

from Basilisk.architecture import messaging
from Basilisk.fswAlgorithms import attTrackingError, hillPoint, mrpFeedback, rwMotorTorque, sunSafePoint
from Basilisk.simulation import (GravityGradientEffector, ReactionWheelPower, eclipse, extForceTorque,
                                 reactionWheelStateEffector, simpleBattery, simpleNav, simplePowerSink,
                                 simpleSolarPanel, spacecraft)
from Basilisk.utilities import (RigidBodyKinematics as rbk, SimulationBaseClass, macros, orbitalMotion,
                                simIncludeGravBody, simIncludeRW)

AU_M = 149597870700.0
R_EARTH_M = 6378136.6

# ---------------------------------------------------------------- spacecraft / mission constants
CFG = dict(
    alt_km=500.0,
    n_orbits=2.0,
    dt_dyn=0.1,            # s, dynamics + FSW rate (RK4)
    chunk_s=5.0,           # s, policy / fault-injection rate
    inertia=[0.12, 0.10, 0.05],
    mass=10.0,
    # zenith-facing body-fixed deployable panel (+X_B); nadir payload on -X_B
    panel_normal_B=[1.0, 0.0, 0.0], panel_area_m2=0.07, panel_eff=0.29,
    battery_Wh=30.0, soc_init=0.65,
    bus_W=3.0, payload_W=4.0, rw_base_W=0.25, rw_elec2mech=0.5,
    nominal_disturbance_Nm=[2e-7, -1e-7, 1.5e-7],    # residual dipole/aero, constant in body
    rw_type="BCT_RWP015",                              # 4 mNm, 15 mNms, 6000 rpm
    rw_axes=[[1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / math.sqrt(3)] * 3],
    rw_init_rpm=[800.0, -600.0, 500.0, -300.0],
    # BSK default omegaLimitCycle=1e-4 rad/s makes the friction term stiff (slope fC/oLC/Js ~ 2e4 1/s) and
    # RK4 at our step goes unstable; widen the linearized-friction band (numerical choice, documented).
    rw_omega_limit_cycle=4.0,
    # gains: wn~0.16 rad/s (max axis), zeta~1; wheel Coulomb friction (no FSW friction compensation) leaves ~2 deg bias
    K=0.012, P=0.04,
    # safety constraints
    soc_floor=0.20,
    att_err_bound_deg=30.0, att_err_max_dur_s=1200.0, att_grace_s=900.0,
    sat_frac=0.98, sat_max_dur_s=60.0,
)

# policy thresholds (the "existing recovery policy" under test)
POLICY = dict(
    soc_shed=0.40,          # below -> payload off + sun-safe
    soc_resume=0.70,        # above (and attitude OK) -> back to nominal
    att_safe_deg=15.0, att_safe_dur_s=120.0,   # nominal attitude error above this for this long -> safe
    fdir_rel=0.25, fdir_abs_Nm=3e-4, fdir_persist=3,   # wheel torque residual detector
    resume_min_s=600.0,     # minimum dwell in safe mode
)

FAULT_KEYS = ("rw_faults", "heater", "torque_leak")

_POLICY_CACHE = {}


def get_policy(name="v1"):
    """'v1' -> POLICY (the original policy; default everywhere, so v1 replays are unchanged);
    'v2' / 'v3' -> data/repair/policy_<name>.json; anything else -> path to a policy json.
    A policy json holds {"name", "params": {...overrides of POLICY + rule keys...}}."""
    if name in (None, "", "v1"):
        return POLICY
    if name not in _POLICY_CACHE:
        import os
        path = name if os.path.exists(name) else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "repair", f"policy_{name}.json")
        d = json.load(open(path))
        _POLICY_CACHE[name] = {**POLICY, **d["params"], "name": d.get("name", name)}
    return _POLICY_CACHE[name]


# fault parameter ranges (shared by random search, grid search and minimization)
RANGES = dict(beta_deg=(0.0, 70.0), f0_deg=(0.0, 360.0), onset_frac=(0.0, 0.8),
              rw_severity=(0.2, 1.0), heater_W=(1.0, 6.0), leak_Nm=(0.3e-6, 1.5e-6))


def default_params():
    return {"orbit": {"beta_deg": 20.0, "f0_deg": 0.0}, "rw_faults": [], "heater": None, "torque_leak": None}


def _hill_sigma(rN, vN):
    r, v = np.array(rN), np.array(vN)
    ir = r / np.linalg.norm(r)
    ih = np.cross(r, v); ih /= np.linalg.norm(ih)
    it = np.cross(ih, ir)
    dcm_HN = np.array([ir, it, ih])
    n = np.linalg.norm(np.cross(r, v)) / np.dot(r, r)
    return rbk.C2MRP(dcm_HN), [0.0, 0.0, n]


def build(params, cfg=CFG):
    sim = SimulationBaseClass.SimBaseClass()
    proc = sim.CreateNewProcess("p")
    dt = macros.sec2nano(cfg["dt_dyn"])
    proc.addTask(sim.CreateNewTask("dyn", dt), 20)
    proc.addTask(sim.CreateNewTask("fsw", dt), 10)

    sc = spacecraft.Spacecraft(); sc.ModelTag = "ffSat"
    sc.hub.mHub = cfg["mass"]
    sc.hub.IHubPntBc_B = np.diag(cfg["inertia"]).tolist()
    sim.AddModelToTask("dyn", sc, 100)

    grav = simIncludeGravBody.gravBodyFactory()
    earth = grav.createEarth(); earth.isCentralBody = True
    grav.addBodiesTo(sc)
    mu = earth.mu

    # static Sun along +X_N, Earth at origin (Sun drift over ~3 h is ~0.1 deg; avoids SPICE per run)
    sunMsg = messaging.SpicePlanetStateMsg().write(messaging.SpicePlanetStateMsgPayload(
        PositionVector=[AU_M, 0, 0], PlanetName="sun"))
    earthMsg = messaging.SpicePlanetStateMsg().write(messaging.SpicePlanetStateMsgPayload(
        PositionVector=[0, 0, 0], PlanetName="earth"))

    # orbit: RAAN=90 deg so inclination == solar beta angle; f0 sets phase vs eclipse
    oe = orbitalMotion.ClassicElements()
    oe.a = R_EARTH_M + cfg["alt_km"] * 1e3; oe.e = 0.0
    oe.i = params["orbit"]["beta_deg"] * macros.D2R
    oe.Omega = 90.0 * macros.D2R; oe.omega = 0.0
    oe.f = params["orbit"]["f0_deg"] * macros.D2R
    rN, vN = orbitalMotion.elem2rv(mu, oe)
    period = 2 * math.pi * math.sqrt(oe.a ** 3 / mu)
    sc.hub.r_CN_NInit = rN; sc.hub.v_CN_NInit = vN
    sig, w = _hill_sigma(rN, vN)
    sc.hub.sigma_BNInit = (np.array(sig) + np.array([0.02, -0.03, 0.02])).reshape(3, 1).tolist()  # ~10 deg off
    sc.hub.omega_BN_BInit = np.array(w).reshape(3, 1).tolist()

    gg = GravityGradientEffector.GravityGradientEffector(); gg.ModelTag = "gg"
    gg.addPlanetName(earth.planetName); sc.addDynamicEffector(gg); sim.AddModelToTask("dyn", gg)
    ext = extForceTorque.ExtForceTorque(); ext.ModelTag = "dist"
    ext.extTorquePntB_B = np.array(cfg["nominal_disturbance_Nm"]).reshape(3, 1).tolist()
    sc.addDynamicEffector(ext); sim.AddModelToTask("dyn", ext)

    rwf = simIncludeRW.rwFactory()
    rws = [rwf.create(cfg["rw_type"], ax, Omega=rpm, useRWfriction=True, RWModel=messaging.BalancedWheels)
           for ax, rpm in zip(cfg["rw_axes"], cfg["rw_init_rpm"])]
    for rw in rws:
        rw.omegaLimitCycle = cfg["rw_omega_limit_cycle"]
    nRW = rwf.getNumOfDevices()
    rwEff = reactionWheelStateEffector.ReactionWheelStateEffector(); rwEff.ModelTag = "rw"
    rwf.addToSpacecraft(sc.ModelTag, rwEff, sc)
    sim.AddModelToTask("dyn", rwEff, 90)

    nav = simpleNav.SimpleNav(); nav.ModelTag = "nav"
    nav.scStateInMsg.subscribeTo(sc.scStateOutMsg); nav.sunStateInMsg.subscribeTo(sunMsg)
    sim.AddModelToTask("dyn", nav)

    ecl = eclipse.Eclipse(); ecl.ModelTag = "ecl"
    ecl.addSpacecraftToModel(sc.scStateOutMsg); ecl.addPlanetToModel(earthMsg); ecl.sunInMsg.subscribeTo(sunMsg)
    sim.AddModelToTask("dyn", ecl)

    panel = simpleSolarPanel.SimpleSolarPanel(); panel.ModelTag = "panel"
    panel.stateInMsg.subscribeTo(sc.scStateOutMsg); panel.sunInMsg.subscribeTo(sunMsg)
    panel.sunEclipseInMsg.subscribeTo(ecl.eclipseOutMsgs[0])
    panel.setPanelParameters(cfg["panel_normal_B"], cfg["panel_area_m2"], cfg["panel_eff"])
    sim.AddModelToTask("dyn", panel)

    sinks = {}
    for name, watts in (("bus", cfg["bus_W"]), ("payload", cfg["payload_W"]), ("heater", 0.0)):
        s = simplePowerSink.SimplePowerSink(); s.ModelTag = name; s.nodePowerOut = -watts
        sim.AddModelToTask("dyn", s); sinks[name] = s
    rwPow = []
    for i in range(nRW):
        p = ReactionWheelPower.ReactionWheelPower(); p.ModelTag = f"rwP{i}"
        p.basePowerNeed = cfg["rw_base_W"]; p.elecToMechEfficiency = cfg["rw_elec2mech"]
        p.rwStateInMsg.subscribeTo(rwEff.rwOutMsgs[i]); sim.AddModelToTask("dyn", p); rwPow.append(p)
    bat = simpleBattery.SimpleBattery(); bat.ModelTag = "bat"
    bat.storageCapacity = cfg["battery_Wh"] * 3600.0
    bat.storedCharge_Init = cfg["soc_init"] * bat.storageCapacity
    bat.addPowerNodeToModel(panel.nodePowerOutMsg)
    for s in sinks.values(): bat.addPowerNodeToModel(s.nodePowerOutMsg)
    for p in rwPow: bat.addPowerNodeToModel(p.nodePowerOutMsg)
    sim.AddModelToTask("dyn", bat)

    # ---- FSW
    vcMsg = messaging.VehicleConfigMsg().write(messaging.VehicleConfigMsgPayload(
        ISCPntB_B=np.diag(cfg["inertia"]).flatten().tolist()))
    rwParamMsg = rwf.getConfigMessage()
    avail = messaging.RWAvailabilityMsgPayload(); avail.wheelAvailability = [messaging.AVAILABLE] * nRW
    availMsg = messaging.RWAvailabilityMsg().write(avail)

    hill = hillPoint.hillPoint(); hill.ModelTag = "hill"
    hill.transNavInMsg.subscribeTo(nav.transOutMsg); sim.AddModelToTask("fsw", hill, 30)
    attErr = attTrackingError.attTrackingError(); attErr.ModelTag = "attErr"
    attErr.attRefInMsg.subscribeTo(hill.attRefOutMsg); attErr.attNavInMsg.subscribeTo(nav.attOutMsg)
    sim.AddModelToTask("fsw", attErr, 25)
    sun = sunSafePoint.sunSafePoint(); sun.ModelTag = "sunSafe"
    sun.sHatBdyCmd = cfg["panel_normal_B"]; sun.minUnitMag = 0.001; sun.smallAngle = 0.001 * macros.D2R
    sun.sunAxisSpinRate = 0.0
    sun.sunDirectionInMsg.subscribeTo(nav.attOutMsg); sun.imuInMsg.subscribeTo(nav.attOutMsg)
    sim.AddModelToTask("fsw", sun, 25)
    ctrl = mrpFeedback.mrpFeedback(); ctrl.ModelTag = "ctrl"
    ctrl.guidInMsg.subscribeTo(attErr.attGuidOutMsg); ctrl.vehConfigInMsg.subscribeTo(vcMsg)
    ctrl.rwParamsInMsg.subscribeTo(rwParamMsg); ctrl.rwSpeedsInMsg.subscribeTo(rwEff.rwSpeedOutMsg)
    ctrl.rwAvailInMsg.subscribeTo(availMsg)
    ctrl.K = cfg["K"]; ctrl.P = cfg["P"]; ctrl.Ki = -1.0
    sim.AddModelToTask("fsw", ctrl, 20)
    mt = rwMotorTorque.rwMotorTorque(); mt.ModelTag = "mt"
    mt.controlAxes_B = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    mt.vehControlInMsg.subscribeTo(ctrl.cmdTorqueOutMsg); mt.rwParamsInMsg.subscribeTo(rwParamMsg)
    mt.rwAvailInMsg.subscribeTo(availMsg)
    sim.AddModelToTask("fsw", mt, 15)
    rwEff.rwMotorCmdInMsg.subscribeTo(mt.rwMotorTorqueOutMsg)

    cmdRec = mt.rwMotorTorqueOutMsg.recorder(dt)
    sim.AddModelToTask("fsw", cmdRec)

    h = dict(sim=sim, sc=sc, rws=rws, rwEff=rwEff, nRW=nRW, sinks=sinks, bat=bat, panel=panel, ecl=ecl,
             ext=ext, attErr=attErr, sun=sun, ctrl=ctrl, mt=mt, availMsg=availMsg, avail=avail,
             cmdRec=cmdRec, nav=nav, period=period, keep=[sunMsg, earthMsg, vcMsg, rwParamMsg, grav, rwf])
    return h


def _angle_deg(sigma):
    return math.degrees(4.0 * math.atan(np.linalg.norm(sigma)))


def run_scenario(params, cfg=CFG, policy=POLICY, telemetry=True, policy_enabled=True, log_attitude=False):
    """Run one simulation. Returns dict with violations, summary metrics and (optionally) telemetry."""
    t_wall0 = time.perf_counter()
    h = build(params, cfg)
    sim, rws, nRW = h["sim"], h["rws"], h["nRW"]
    sim.InitializeSimulation()
    u_max0 = [rw.u_max for rw in rws]
    fC0 = [rw.fCoulomb for rw in rws]
    Js = [rw.Js for rw in rws]
    Om_max = [rw.Omega_max for rw in rws]
    capJ = cfg["battery_Wh"] * 3600.0
    T_end = cfg["n_orbits"] * h["period"]
    chunk = cfg["chunk_s"]

    # fault schedule
    events = []
    for k, f in enumerate(params.get("rw_faults") or []):
        events.append((f["onset_s"], "rw", k, f))
    if params.get("heater"):
        events.append((params["heater"]["onset_s"], "heater", 0, params["heater"]))
    if params.get("torque_leak"):
        events.append((params["torque_leak"]["onset_s"], "leak", 0, params["torque_leak"]))
    events.sort(key=lambda e: e[0])
    applied = set()

    st = dict(mode="NOMINAL", payload=True, avail=[True] * nRW, res_cnt=[0] * nRW, att_bad_s=0.0,
              safe_since=None, iso_res=[0.0] * nRW)
    log = []           # policy actions
    tel = []
    att_log = []       # optional: [t, sigma_BR(3), sigma_BN(3)] for visualisation (log_attitude=True)
    prev_Om = [rw.Omega for rw in rws]
    sat_s = [0.0] * nRW
    att_bad_run = 0.0
    viol = {}

    t = 0.0
    while t < T_end - 1e-9:
        # ---- fault injection at chunk boundaries (onset quantized to chunk_s)
        for (ton, kind, k, f) in events:
            if (kind, k) in applied or ton > t + 1e-9:
                continue
            applied.add((kind, k))
            if kind == "rw":
                rw = rws[f["wheel"]]
                if f["type"] == "torque_derate":
                    rw.u_max = max(u_max0[f["wheel"]] * (1.0 - f["severity"]), 1e-9)  # u_max<=0 means unlimited in BSK
                elif f["type"] == "friction":
                    rw.fCoulomb = rw.fCoulomb + f["severity"] * 2e-3
                    rw.cViscous = rw.cViscous + f["severity"] * 2e-6
            elif kind == "heater":
                h["sinks"]["heater"].nodePowerOut = -f["power_W"]
            elif kind == "leak":
                ax = np.array(f["axis"], float); ax /= np.linalg.norm(ax)
                tq = np.array(cfg["nominal_disturbance_Nm"]) + f["mag_Nm"] * ax
                h["ext"].extTorquePntB_B = tq.reshape(3, 1).tolist()
            log.append((t, f"FAULT {kind}{k} applied {json.dumps(f)}"))

        sim.ConfigureStopTime(macros.sec2nano(t + chunk))
        sim.ExecuteSimulation()
        t += chunk

        # ---- read state
        bat = h["bat"].batPowerOutMsg.read()
        soc = bat.storageLevel / capJ
        guid = (h["attErr"].attGuidOutMsg if st["mode"] == "NOMINAL" else h["sun"].attGuidanceOutMsg).read()
        err_deg = _angle_deg(guid.sigma_BR)
        Om = [rw.Omega for rw in rws]
        cmds = np.array(h["cmdRec"].motorTorque)[:, :nRW] if len(h["cmdRec"].times()) else np.zeros((1, nRW))
        h["cmdRec"].clear()
        u_mean = cmds.mean(axis=0)

        # ---- policy
        if policy_enabled:
            # FDIR: per-wheel torque residual from wheel-speed change vs commanded torque
            for i in range(nRW):
                if not st["avail"][i]:
                    continue
                delivered = Js[i] * (Om[i] - prev_Om[i]) / chunk
                res = abs(u_mean[i] - delivered)
                if res > max(policy["fdir_rel"] * abs(u_mean[i]), policy["fdir_abs_Nm"]):
                    st["res_cnt"][i] += 1
                else:
                    st["res_cnt"][i] = 0
                if st["res_cnt"][i] >= policy["fdir_persist"] and sum(st["avail"]) > policy.get("min_avail", 3):
                    st["avail"][i] = False
                    st["iso_res"][i] = res
                    h["avail"].wheelAvailability = [messaging.AVAILABLE if a else messaging.UNAVAILABLE
                                                    for a in st["avail"]]
                    h["availMsg"].write(h["avail"])
                    log.append((t, f"POLICY FDIR: wheel {i} isolated (residual {res:.2e} Nm)"))
                elif st["res_cnt"][i] >= policy["fdir_persist"] and policy.get("isolation_swap", False):
                    # v2 rule: keep 3-wheel control with the healthiest wheels - if a new wheel is clearly worse
                    # than an already-isolated one, re-enable the isolated (milder) wheel and isolate the new one
                    iso = [k for k in range(nRW) if not st["avail"][k]]
                    if iso:
                        k = min(iso, key=lambda q: st["iso_res"][q])
                        smin, imax = policy.get("swap_min_res_Nm"), policy.get("swap_max_iso_res_Nm")
                        if (res > policy.get("swap_ratio", 2.0) * st["iso_res"][k]
                                and (smin is None or res >= smin) and (imax is None or st["iso_res"][k] <= imax)):
                            st["avail"][k], st["avail"][i] = True, False
                            st["iso_res"][i] = res
                            st["res_cnt"][k] = 0
                            h["avail"].wheelAvailability = [messaging.AVAILABLE if a else messaging.UNAVAILABLE
                                                            for a in st["avail"]]
                            h["availMsg"].write(h["avail"])
                            log.append((t, f"POLICY FDIR: swap - wheel {k} re-enabled, wheel {i} isolated "
                                           f"(residual {res:.2e} > {policy.get('swap_ratio', 2.0)} x {st['iso_res'][k]:.2e} Nm)"))
            # v2 rule (momentum guard): an in-use wheel above wheel_safe_frac of max speed for wheel_safe_s -> SAFE
            wsf = policy.get("wheel_safe_frac")
            if wsf:
                hi = any(st["avail"][i] and abs(Om[i]) >= wsf * Om_max[i] for i in range(nRW))
                st["wheel_hi_s"] = st.get("wheel_hi_s", 0.0) + chunk if hi else 0.0
            # attitude watchdog in nominal
            if st["mode"] == "NOMINAL":
                st["att_bad_s"] = st["att_bad_s"] + chunk if err_deg > policy["att_safe_deg"] else 0.0
            go_safe = None
            if st["mode"] == "NOMINAL" and soc < policy["soc_shed"]:
                go_safe = f"SoC {soc:.2f} < {policy['soc_shed']}"
            if st["mode"] == "NOMINAL" and st["att_bad_s"] >= policy["att_safe_dur_s"] and t > cfg["att_grace_s"]:
                go_safe = f"attitude error {err_deg:.1f} deg > {policy['att_safe_deg']} for {st['att_bad_s']:.0f}s"
            if (wsf and st["mode"] == "NOMINAL" and st.get("wheel_hi_s", 0.0) >= policy.get("wheel_safe_s", 30.0)
                    and not go_safe):
                go_safe = f"wheel speed >= {wsf:.0%} of max for {st['wheel_hi_s']:.0f}s"
            if go_safe:
                st.update(mode="SAFE", payload=False, safe_since=t, att_bad_s=0.0)
                h["sinks"]["payload"].nodePowerOut = 0.0
                h["ctrl"].guidInMsg.subscribeTo(h["sun"].attGuidanceOutMsg)
                log.append((t, f"POLICY -> SAFE (sun-point, payload off): {go_safe}"))
            elif (st["mode"] == "SAFE" and soc > policy["soc_resume"] and err_deg < policy["att_safe_deg"]
                  and t - st["safe_since"] >= policy["resume_min_s"]
                  and not (wsf and st.get("wheel_hi_s", 0.0) > 0)):
                st.update(mode="NOMINAL", payload=True, att_bad_s=0.0)
                h["sinks"]["payload"].nodePowerOut = -cfg["payload_W"]
                h["ctrl"].guidInMsg.subscribeTo(h["attErr"].attGuidOutMsg)
                log.append((t, f"POLICY -> NOMINAL (SoC {soc:.2f})"))
        prev_Om = Om

        # ---- safety constraints
        if soc < cfg["soc_floor"] and "battery_floor" not in viol:
            viol["battery_floor"] = t
        if t > cfg["att_grace_s"]:
            att_bad_run = att_bad_run + chunk if err_deg > cfg["att_err_bound_deg"] else 0.0
            if att_bad_run > cfg["att_err_max_dur_s"] and "attitude_loss" not in viol:
                viol["attitude_loss"] = t
        for i in range(nRW):
            if st["avail"][i] and abs(Om[i]) >= cfg["sat_frac"] * Om_max[i]:
                sat_s[i] += chunk
                if sat_s[i] > cfg["sat_max_dur_s"] and "wheel_saturation" not in viol:
                    viol["wheel_saturation"] = t

        if telemetry and (int(round(t)) % 10 == 0):
            tel.append([t, soc, h["panel"].nodePowerOutMsg.read().netPower, bat.currentNetPower, err_deg,
                        1 if st["mode"] == "SAFE" else 0, h["ecl"].eclipseOutMsgs[0].read().shadowFactor]
                       + [o * 60 / (2 * math.pi) for o in Om] + [1 if a else 0 for a in st["avail"]])
        if log_attitude and (int(round(t)) % 10 == 0):
            sBN = list(h["sc"].scStateOutMsg.read().sigma_BN)
            att_log.append([t] + list(guid.sigma_BR) + sBN)
        # min SoC tracking + near-miss margins (tracked before the early exit so they are always complete)
        st["min_soc"] = min(st.get("min_soc", 1.0), soc)
        st["max_err_late"] = max(st.get("max_err_late", 0.0), err_deg if t > cfg["att_grace_s"] else 0.0)
        st["max_att_run"] = max(st.get("max_att_run", 0.0), att_bad_run)
        st["max_wheel_ratio"] = max([st.get("max_wheel_ratio", 0.0)] + [abs(Om[i]) / Om_max[i] for i in range(nRW)
                                                                        if st["avail"][i]])
        st["max_sat_run"] = max([st.get("max_sat_run", 0.0)] + sat_s)
        if not telemetry and len(viol) == 3:
            break

    wall = time.perf_counter() - t_wall0
    out = dict(params=params, violations=viol, violated=bool(viol), min_soc=st["min_soc"],
               max_att_err_after_grace_deg=st["max_err_late"], final_mode=st["mode"],
               isolated_wheels=[i for i, a in enumerate(st["avail"]) if not a], sim_time_s=t,
               wall_s=wall, policy_log=log,
               # near-miss margins: <0 / >=1 means the constraint was crossed (see CFG for thresholds)
               margins=dict(
                   battery_margin=round(st["min_soc"] - cfg["soc_floor"], 5),              # SoC above floor
                   att_err_ratio=round(st["max_err_late"] / cfg["att_err_bound_deg"], 5),  # peak err / bound
                   att_dur_ratio=round(st["max_att_run"] / cfg["att_err_max_dur_s"], 5),   # out-of-bound run / limit
                   wheel_speed_ratio=round(st["max_wheel_ratio"] / cfg["sat_frac"], 5),    # peak |Omega| / sat thr
                   sat_dur_ratio=round(st["max_sat_run"] / cfg["sat_max_dur_s"], 5)),
               n_policy_actions=sum(1 for _, m in log if m.startswith("POLICY")))
    if telemetry:
        out["telemetry_cols"] = (["t_s", "soc", "panel_W", "net_W", "att_err_deg", "safe_mode", "sunlit"]
                                 + [f"rw{i}_rpm" for i in range(nRW)] + [f"rw{i}_avail" for i in range(nRW)])
        out["telemetry"] = tel
    if log_attitude:
        out["attitude_cols"] = ["t_s", "sBR1", "sBR2", "sBR3", "sBN1", "sBN2", "sBN3"]
        out["attitude"] = att_log
    return out


if __name__ == "__main__":
    r = run_scenario(default_params())
    print(json.dumps({k: v for k, v in r.items() if k not in ("telemetry",)}, indent=1, default=str))
