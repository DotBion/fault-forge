"""Re-run the minimized headline case (default a6e8087b7a52c977) for demo video v4, segment 1:
full v1 policy vs v1 with ONLY wheel isolation suppressed (suppress_isolation=True; same arms as src/causal_replay.py).

    python3 demo/replay_causal_v4.py [KEY]

Reads the minimized params from data/cmp/minimized.jsonl; writes demo/data/hl4_{full,no_isolate}.csv
(telemetry + sigma_BR/sigma_BN) and demo/data/hl4_runs.json. Uses the corrected (consecutive) saturation rule."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import ff_sim

KEY = sys.argv[1] if len(sys.argv) > 1 else "a6e8087b7a52c977"
OUT = os.path.join(HERE, "data"); os.makedirs(OUT, exist_ok=True)
mn = next(json.loads(l) for l in open(os.path.join(ROOT, "data/cmp/minimized.jsonl")) if json.loads(l)["key"] == KEY)
params = mn["minimized"]
pol = ff_sim.get_policy("v1")
meta = {"key": KEY, "params": params, "sat_rule": ff_sim.CFG.get("sat_rule"),
        "minimized_record": {k: v for k, v in mn.items() if k != "minimized"}}
for tag, p in (("full", pol), ("no_isolate", {**pol, "suppress_isolation": True})):
    r = ff_sim.run_scenario(params, policy=p, policy_enabled=True, log_attitude=True)
    att = {row[0]: row[1:] for row in r["attitude"]}
    cols = r["telemetry_cols"] + r["attitude_cols"][1:]
    with open(os.path.join(OUT, f"hl4_{tag}.csv"), "w") as f:
        f.write(",".join(cols) + "\n")
        for row in r["telemetry"]:
            f.write(",".join(f"{v:.6g}" for v in row + att.get(row[0], [float("nan")] * 6)) + "\n")
    meta[tag] = dict(violations=r["violations"], policy_log=[[t, m] for t, m in r["policy_log"]],
                     max_att_err_after_grace_deg=r["max_att_err_after_grace_deg"], margins=r["margins"])
    print(tag, r["violations"], round(r["max_att_err_after_grace_deg"], 2), flush=True)
json.dump(meta, open(os.path.join(OUT, "hl4_runs.json"), "w"), indent=1)
