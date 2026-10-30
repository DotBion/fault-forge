"""Re-run the headline counterexample (data/repair/headline_v2.json) with attitude logging for the demo video.
Writes demo/data/headline_{v1,v1_nopolicy,v2}.csv (telemetry + sigma_BR/sigma_BN) and headline_runs.json."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import ff_sim

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(os.path.dirname(__file__), "data"); os.makedirs(OUT, exist_ok=True)
hl = json.load(open(os.path.join(ROOT, "data/repair/headline_v2.json")))
runs = {"v1": ("v1", True), "v1_nopolicy": ("v1", False), "v2": ("v2", True)}
meta = {"key": hl["key"], "params": hl["params"]}
for tag, (pol, on) in runs.items():
    r = ff_sim.run_scenario(hl["params"], policy=ff_sim.get_policy(pol), policy_enabled=on, log_attitude=True)
    att = {row[0]: row[1:] for row in r["attitude"]}
    cols = r["telemetry_cols"] + r["attitude_cols"][1:]
    with open(os.path.join(OUT, f"headline_{tag}.csv"), "w") as f:
        f.write(",".join(cols) + "\n")
        for row in r["telemetry"]:
            f.write(",".join(f"{v:.6g}" for v in row + att.get(row[0], [float("nan")] * 6)) + "\n")
    meta[tag] = dict(violations=r["violations"], policy_log=[[t, m] for t, m in r["policy_log"]],
                     max_att_err_after_grace_deg=r["max_att_err_after_grace_deg"], margins=r["margins"])
    print(tag, r["violations"], round(r["max_att_err_after_grace_deg"], 2))
json.dump(meta, open(os.path.join(OUT, "headline_runs.json"), "w"), indent=1)
