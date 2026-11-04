"""Empirical proposal distribution of the Muse-guided arm (data/cmp/muse_seed{0,1,2}.jsonl), compared to the
uniform random baseline (data/cmp/random_seed*.jsonl). Writes data/matched/muse_distribution.json.

  python3 src/muse_distribution.py
Only rows with source == "muse" count as Muse proposals (random fallbacks are excluded).
"""
import collections
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search import T_end  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(arm, muse_only=False):
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "cmp", f"{arm}_seed[0-9].jsonl"))):
        for l in open(p):
            r = json.loads(l)
            if muse_only and r.get("source", "muse") != "muse":
                continue
            rows.append(r)
    return rows


def q(x):
    x = np.asarray(x, float)
    if not len(x):
        return None
    return {"n": int(len(x)), "mean": float(x.mean()), "std": float(x.std()),
            "p05_25_50_75_95": [float(v) for v in np.percentile(x, [5, 25, 50, 75, 95])],
            "min": float(x.min()), "max": float(x.max())}


def describe(rows):
    Te = T_end()
    n = len(rows)
    nrw = collections.Counter(len(r["params"]["rw_faults"]) for r in rows)
    nf = collections.Counter(len(r["params"]["rw_faults"]) + (r["params"]["heater"] is not None)
                             + (r["params"]["torque_leak"] is not None) for r in rows)
    combo = collections.Counter("+".join(sorted([f"rw_{f['type']}" for f in r["params"]["rw_faults"]]
                                                + (["heater"] if r["params"]["heater"] else [])
                                                + (["leak"] if r["params"]["torque_leak"] else []))) or "none"
                                for r in rows)
    rwtypes = collections.Counter("+".join(sorted(f["type"] for f in r["params"]["rw_faults"]))
                                  for r in rows if r["params"]["rw_faults"])
    wheels = collections.Counter(f["wheel"] for r in rows for f in r["params"]["rw_faults"])
    ftype = collections.Counter(f["type"] for r in rows for f in r["params"]["rw_faults"])
    sev = {t: q([f["severity"] for r in rows for f in r["params"]["rw_faults"] if f["type"] == t]) for t in ftype}
    sev_raw = {t: [f["severity"] for r in rows for f in r["params"]["rw_faults"] if f["type"] == t] for t in ftype}
    onset_rw = [f["onset_s"] / Te for r in rows for f in r["params"]["rw_faults"]]
    heat = [r["params"]["heater"] for r in rows if r["params"]["heater"]]
    leak = [r["params"]["torque_leak"] for r in rows if r["params"]["torque_leak"]]
    two_onset_gap = [abs(r["params"]["rw_faults"][0]["onset_s"] - r["params"]["rw_faults"][1]["onset_s"]) / Te
                     for r in rows if len(r["params"]["rw_faults"]) == 2]
    return {
        "n_proposals": n,
        "rw_fault_count": {k: nrw[k] / n for k in sorted(nrw)},
        "two_wheel_fraction": nrw.get(2, 0) / n,
        "total_fault_count": {k: nf[k] / n for k in sorted(nf)},
        "heater_fraction": len(heat) / n, "leak_fraction": len(leak) / n,
        "rw_fault_type_share": {k: v / max(sum(ftype.values()), 1) for k, v in ftype.items()},
        "rw_type_combo_given_rw": {k: v / max(sum(rwtypes.values()), 1) for k, v in rwtypes.most_common()},
        "fault_kind_combo": {k: v / n for k, v in combo.most_common()},
        "wheel_index_share": {k: wheels[k] / max(sum(wheels.values()), 1) for k in sorted(wheels)},
        "beta_deg": q([r["params"]["orbit"]["beta_deg"] for r in rows]),
        "f0_deg": q([r["params"]["orbit"]["f0_deg"] for r in rows]),
        "rw_onset_frac": q(onset_rw),
        "rw_onset_gap_frac_two_wheel": q(two_onset_gap),
        "rw_severity_by_type": sev,
        "rw_severity_at_1.0_share": {t: float(np.mean(np.isclose(v, 1.0))) for t, v in sev_raw.items()},
        "heater_onset_frac": q([h["onset_s"] / Te for h in heat]),
        "heater_power_W": q([h["power_W"] for h in heat]),
        "leak_onset_frac": q([x["onset_s"] / Te for x in leak]),
        "leak_mag_Nm": q([x["mag_Nm"] for x in leak]),
        "leak_axis_dominant": dict(collections.Counter(
            ("+" if x["axis"][int(np.argmax(np.abs(x["axis"])))] > 0 else "-") + "XYZ"[int(np.argmax(np.abs(x["axis"])))]
            for x in leak).most_common()),
    }


def main():
    out = {"muse_all_seeds": describe(load("muse", muse_only=True)),
           "muse_per_seed": {}, "random_all_seeds": describe(load("random")),
           "museblind_all_seeds": describe(load("museblind", muse_only=True)), "T_end_s": T_end()}
    for s in (0, 1, 2):
        rows = [r for r in load("muse", muse_only=True) if r["seed"] == s]
        out["muse_per_seed"][s] = {k: describe(rows)[k] for k in ("n_proposals", "two_wheel_fraction", "rw_fault_count",
                                                                   "heater_fraction", "leak_fraction")}
    allm = load("muse")
    out["muse_fallback_rows"] = sum(1 for r in allm if r.get("source") != "muse")
    p = os.path.join(ROOT, "data", "matched", "muse_distribution.json")
    json.dump(out, open(p, "w"), indent=1)
    m, r = out["muse_all_seeds"], out["random_all_seeds"]
    print("wrote", p)
    for k in ("n_proposals", "two_wheel_fraction", "rw_fault_count", "total_fault_count", "heater_fraction",
              "leak_fraction", "rw_fault_type_share"):
        print(f"{k:24s} muse={m[k]}  random={r[k]}")
    print("muse combos:", {k: round(v, 3) for k, v in list(m["fault_kind_combo"].items())[:12]})
    print("muse rw type combos:", m["rw_type_combo_given_rw"])
    print("wheel share:", m["wheel_index_share"])
    for k in ("beta_deg", "f0_deg", "rw_onset_frac", "rw_onset_gap_frac_two_wheel", "rw_severity_by_type", "rw_severity_at_1.0_share",
              "heater_onset_frac", "heater_power_W", "leak_onset_frac", "leak_mag_Nm", "leak_axis_dominant"):
        print(k, json.dumps(m[k]))
    print("per seed", json.dumps(out["muse_per_seed"]))
    print("fallback rows", out["muse_fallback_rows"])


if __name__ == "__main__":
    main()
