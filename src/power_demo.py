"""Re-run of Basilisk's stock examples/scenarioPowerDemo.py (bsk 2.12.1) with telemetry export.

The simulation setup below is copied verbatim (modulo comments) from
https://github.com/AVSLab/basilisk/blob/v2.12.1/examples/scenarioPowerDemo.py (ISC license),
so the numbers are the stock scenario's. Only the CSV/PNG export at the end is new.

Usage:  python src/power_demo.py   ->  data/power_demo.csv, plots/power_demo.png
"""
import os
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from Basilisk.utilities import SimulationBaseClass, macros, orbitalMotion, simIncludeGravBody
from Basilisk.simulation import simplePowerSink, simpleBattery, simpleSolarPanel, eclipse, spacecraft
from Basilisk.architecture import astroConstants

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run():
    taskName, processname = "unitTask", "TestProcess"
    scenarioSim = SimulationBaseClass.SimBaseClass()
    testProc = scenarioSim.CreateNewProcess(processname)
    testProc.addTask(scenarioSim.CreateNewTask(taskName, macros.sec2nano(1.0)))

    scObject = spacecraft.Spacecraft()
    scObject.ModelTag = "bsk-Sat"
    gravFactory = simIncludeGravBody.gravBodyFactory()
    planet = gravFactory.createEarth()
    planet.isCentralBody = True
    mu = planet.mu
    gravFactory.createSun()
    gravFactory.addBodiesTo(scObject)
    spiceObject = gravFactory.createSpiceInterface(time='2021 MAY 04 07:47:48.965 (UTC)')
    scenarioSim.AddModelToTask(taskName, spiceObject, -1)
    plMsg = spiceObject.planetStateOutMsgs[0]
    sunMsg = spiceObject.planetStateOutMsgs[1]

    oe = orbitalMotion.ClassicElements()
    oe.a = astroConstants.REQ_EARTH * 1e3 + 400e3
    oe.e = 0.0
    oe.i = 0.0
    oe.Omega = 0.0
    oe.omega = 0.0
    oe.f = 75.0 * macros.D2R
    rN, vN = orbitalMotion.elem2rv(mu, oe)
    P = 2. * np.pi / np.sqrt(mu / oe.a ** 3)
    scObject.hub.r_CN_NInit = rN
    scObject.hub.v_CN_NInit = vN
    scObject.hub.sigma_BNInit = [[0.1], [0.2], [-0.3]]
    scObject.hub.omega_BN_BInit = [[0.001], [-0.001], [0.001]]
    scenarioSim.AddModelToTask(taskName, scObject)

    eclipseObject = eclipse.Eclipse()
    eclipseObject.addSpacecraftToModel(scObject.scStateOutMsg)
    eclipseObject.addPlanetToModel(plMsg)
    eclipseObject.sunInMsg.subscribeTo(sunMsg)
    scenarioSim.AddModelToTask(taskName, eclipseObject)

    solarPanel = simpleSolarPanel.SimpleSolarPanel()
    solarPanel.ModelTag = "solarPanel"
    solarPanel.stateInMsg.subscribeTo(scObject.scStateOutMsg)
    solarPanel.sunEclipseInMsg.subscribeTo(eclipseObject.eclipseOutMsgs[0])
    solarPanel.sunInMsg.subscribeTo(sunMsg)
    solarPanel.setPanelParameters([1, 0, 0], 0.2 * 0.3, 0.20)
    scenarioSim.AddModelToTask(taskName, solarPanel)

    powerSink = simplePowerSink.SimplePowerSink()
    powerSink.ModelTag = "powerSink2"
    powerSink.nodePowerOut = -3.
    scenarioSim.AddModelToTask(taskName, powerSink)

    powerMonitor = simpleBattery.SimpleBattery()
    powerMonitor.ModelTag = "powerMonitor"
    powerMonitor.storageCapacity = 10.0 * 3600.0
    powerMonitor.storedCharge_Init = 10.0 * 3600.0
    powerMonitor.addPowerNodeToModel(solarPanel.nodePowerOutMsg)
    powerMonitor.addPowerNodeToModel(powerSink.nodePowerOutMsg)
    scenarioSim.AddModelToTask(taskName, powerMonitor)

    spLog = solarPanel.nodePowerOutMsg.recorder()
    psLog = powerSink.nodePowerOutMsg.recorder()
    pmLog = powerMonitor.batPowerOutMsg.recorder()
    ecLog = eclipseObject.eclipseOutMsgs[0].recorder()
    for r in (spLog, psLog, pmLog, ecLog):
        scenarioSim.AddModelToTask(taskName, r)

    scenarioSim.InitializeSimulation()
    scenarioSim.ConfigureStopTime(macros.sec2nano(P))
    t0 = time.perf_counter()
    scenarioSim.ExecuteSimulation()
    wall = time.perf_counter() - t0

    t_s = spLog.times() * macros.NANO2SEC
    return dict(t_s=t_s, panel_W=spLog.netPower, load_W=psLog.netPower,
                net_W=pmLog.currentNetPower, stored_J=pmLog.storageLevel,
                shadow_factor=ecLog.shadowFactor), P, wall


def main():
    d, P, wall = run()
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "plots"), exist_ok=True)
    csv = os.path.join(ROOT, "data", "power_demo.csv")
    cols = ["t_s", "panel_W", "load_W", "net_W", "stored_J", "shadow_factor"]
    np.savetxt(csv, np.column_stack([d[c] for c in cols]), delimiter=",", header=",".join(cols),
               comments="", fmt="%.6g")
    th = d["t_s"] / 3600.
    fig, ax = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    ax[0].plot(th, d["stored_J"] / 3600., label="Stored energy (Wh)")
    ax[0].set_ylabel("Wh"); ax[0].grid(True); ax[0].legend()
    ax[1].plot(th, d["panel_W"], label="Panel power (W)")
    ax[1].plot(th, d["load_W"], label="Load (W)")
    ax[1].plot(th, d["net_W"], label="Net power (W)")
    ax[1].plot(th, d["shadow_factor"] * 3, "k:", label="Sunlit (shadowFactor x3)")
    ax[1].set_xlabel("Time (h)"); ax[1].set_ylabel("W"); ax[1].grid(True); ax[1].legend(fontsize=8)
    fig.suptitle("Basilisk scenarioPowerDemo (stock), 1 orbit @ 400 km")
    fig.tight_layout()
    png = os.path.join(ROOT, "plots", "power_demo.png")
    fig.savefig(png, dpi=120)
    print(f"orbit period {P:.1f} s, sim wall time {wall:.2f} s, {len(th)} samples")
    print(f"stored energy start {d['stored_J'][0]/3600:.3f} Wh, min {d['stored_J'].min()/3600:.3f} Wh, end {d['stored_J'][-1]/3600:.3f} Wh")
    print(f"panel power max {d['panel_W'].max():.3f} W, mean {d['panel_W'].mean():.3f} W; sunlit fraction {np.mean(d['shadow_factor']>0.5):.3f}")
    print("wrote", csv, png)


if __name__ == "__main__":
    main()
