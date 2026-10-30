"""Replay one run (from a search jsonl by id, or from a params JSON file) with full telemetry.

  python src/replay.py data/random_seed0.jsonl 17          # run id 17 of that search
  python src/replay.py data/minimal_random_seed0_17.json    # a minimized counterexample
  python src/replay.py data/repair/headline_v2.json --policy v2   # headline case under the repaired policy
  python src/replay.py --nominal                             # no faults, default orbit

Writes data/replay_<tag>.csv and plots/replay_<tag>.png and checks the violations match the record.
"""
import argparse
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path, rid):
    if path.endswith(".jsonl"):
        for line in open(path):
            r = json.loads(line)
            if r["id"] == rid:
                return r["params"], r.get("violations"), f"{os.path.basename(path)[:-6]}_{rid}"
        raise SystemExit(f"id {rid} not in {path}")
    d = json.load(open(path))
    return d["params"], d.get("violations"), os.path.basename(path)[:-5]


def plot(res, tag, title=None):
    T = np.array(res["telemetry"]); c = {n: i for i, n in enumerate(res["telemetry_cols"])}
    th = T[:, c["t_s"]] / 3600
    fig, ax = plt.subplots(4, 1, figsize=(10, 10), sharex=True)
    ax[0].plot(th, 100 * T[:, c["soc"]], label="SoC %")
    ax[0].axhline(100 * ff_sim.CFG["soc_floor"], color="r", ls="--", label="floor")
    ax[0].axhline(100 * ff_sim.POLICY["soc_shed"], color="orange", ls=":", label="policy shed")
    ax[0].set_ylabel("battery %"); ax[0].legend(fontsize=8)
    ax[1].plot(th, T[:, c["panel_W"]], label="panel W"); ax[1].plot(th, T[:, c["net_W"]], label="net W")
    ax[1].fill_between(th, -20, 40, where=T[:, c["sunlit"]] < 0.5, color="k", alpha=0.12, label="eclipse")
    ax[1].set_ylim(-20, 32); ax[1].set_ylabel("W"); ax[1].legend(fontsize=8)
    ax[2].semilogy(th, np.maximum(T[:, c["att_err_deg"]], 1e-2), label="att. error vs active ref (deg)")
    ax[2].axhline(ff_sim.CFG["att_err_bound_deg"], color="r", ls="--", label="bound")
    ax[2].fill_between(th, 1e-2, 200, where=T[:, c["safe_mode"]] > 0.5, color="g", alpha=0.12, label="SAFE mode")
    ax[2].set_ylabel("deg"); ax[2].legend(fontsize=8)
    for i in range(4):
        ax[3].plot(th, T[:, c[f"rw{i}_rpm"]], label=f"RW{i}" + ("" if T[-1, c[f"rw{i}_avail"]] else " (isolated)"))
    ax[3].axhline(6000 * ff_sim.CFG["sat_frac"], color="r", ls="--"); ax[3].axhline(-6000 * ff_sim.CFG["sat_frac"], color="r", ls="--")
    ax[3].set_ylabel("wheel rpm"); ax[3].set_xlabel("time (h)"); ax[3].legend(fontsize=8, ncol=4)
    fig.suptitle(title or f"{tag}: violations={res['violations']}", fontsize=10)
    fig.tight_layout()
    png = os.path.join(ROOT, "plots", f"replay_{tag}.png"); fig.savefig(png, dpi=110); plt.close(fig)
    csv = os.path.join(ROOT, "data", f"replay_{tag}.csv")
    np.savetxt(csv, T, delimiter=",", header=",".join(res["telemetry_cols"]), comments="", fmt="%.6g")
    return png, csv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?"); ap.add_argument("id", nargs="?", type=int)
    ap.add_argument("--nominal", action="store_true"); ap.add_argument("--no-policy", action="store_true")
    ap.add_argument("--policy", default=os.environ.get("FF_POLICY", "v1"), help="v1 (default) | v2 | v3 | policy json")
    a = ap.parse_args()
    if a.nominal:
        params, rec, tag = ff_sim.default_params(), {}, "nominal"
    else:
        params, rec, tag = load(a.path, a.id)
    if a.no_policy:
        tag += "_nopolicy"
    elif a.policy not in ("", "v1"):
        tag += f"_{os.path.basename(a.policy).replace('.json', '')}"
    print("params:", json.dumps(params))
    res = ff_sim.run_scenario(params, policy=ff_sim.get_policy(a.policy), policy_enabled=not a.no_policy)
    for t, msg in res["policy_log"]:
        print(f"  t={t:7.0f}s  {msg}")
    print("violations:", res["violations"], "| min SoC %.3f" % res["min_soc"], "| wall %.2fs" % res["wall_s"])
    if rec is not None and not a.no_policy and not a.nominal:
        same = set(rec) == set(res["violations"]) and all(abs(rec[k] - res["violations"][k]) < 1e-6 for k in rec)
        print("matches recorded result:", same)
    png, csv = plot(res, tag)
    print("wrote", png, csv)


if __name__ == "__main__":
    main()
