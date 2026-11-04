"""Equal-budget comparison of search arms (Muse-guided, rules-blind Muse, CMA-ES, random), with minimization + dedupe.

  python src/compare.py --workers 8
reads   data/cmp/<arm>_seed<s>.jsonl  (arms: muse, museblind, cmaes, random)
writes  data/cmp/minimized.jsonl (cache: one minimized counterexample per violating run, + no-policy check)
        data/cmp/summary.json, plots/arms_comparison.png

Out-of-scope (for a single-fault-tolerant policy): the minimized case needs >= 2 nearly dead wheels
(>= 2 torque_derate faults with severity >= 0.9). Reported per arm as a share of reproducing minimized cases.

Pattern of a minimized counterexample:
  coarse = target violation <- sorted fault kinds (rw_torque_derate / rw_friction / heater / leak)
  fine   = target violation <- sorted faults with wheel index / dominant leak axis (+X, -Z, ...)
"""
import argparse
import glob
import hashlib
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
import minimize as M  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMP = os.path.join(ROOT, "data", "cmp")


SAT = "wheel_saturation"


def phash(p):
    return hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]


def leak_axis(ax):
    i = int(np.argmax(np.abs(ax)))
    return ("+" if ax[i] > 0 else "-") + "XYZ"[i]


def patterns(target, p):
    kinds, fine = [], []
    for f in p["rw_faults"]:
        kinds.append(f"rw_{f['type']}"); fine.append(f"rw{f['wheel']}_{f['type']}")
    if p["heater"]:
        kinds.append("heater"); fine.append("heater")
    if p["torque_leak"]:
        kinds.append("leak"); fine.append("leak" + leak_axis(p["torque_leak"]["axis"]))
    return target + " <- " + "+".join(sorted(kinds)), target + " <- " + "+".join(sorted(fine))


def out_of_scope(m):
    return sum(1 for f in m["minimized"]["rw_faults"] if f["type"] == "torque_derate" and f["severity"] >= 0.9) >= 2


def _minimize(job):
    key, params, viol = job
    target = min(viol, key=viol.get)
    n0 = M.N_SIMS[0]
    m = M.minimize(params, target, log=lambda *a: None)
    r = ff_sim.run_scenario(m, telemetry=False)
    r_np = ff_sim.run_scenario(m, telemetry=False, policy_enabled=False)
    co, fi = patterns(target, m)
    return {"key": key, "sat_rule": ff_sim.CFG["sat_rule"], "target": target, "minimized": m, "violations": r["violations"],
            "reproduces": target in r["violations"], "policy_induced": target not in r_np["violations"],
            "violations_no_policy": r_np["violations"], "n_faults_before": len(M.components(params)),
            "n_faults_after": len(M.components(m)), "minimization_sims": M.N_SIMS[0] - n0 + 2,
            "pattern_coarse": co, "pattern_fine": fi}


def load_runs():
    arms = {}
    for path in sorted(glob.glob(os.path.join(CMP, "*_seed*.jsonl"))):
        if path.endswith("_calls.jsonl"):
            continue
        name = os.path.basename(path)[:-6]
        arm, seed = name.split("_seed")
        rows = sorted((json.loads(l) for l in open(path)), key=lambda r: r["id"])
        arms.setdefault(arm, {})[int(seed)] = rows
    # equal budget per seed: truncate every arm to the shortest arm for that seed (random runs are i.i.d. per id,
    # so the first N random runs are a valid N-sim random search)
    for s in set().union(*[set(v) for v in arms.values()]):
        n = min(len(arms[a][s]) for a in arms if s in arms[a])
        for a in arms:
            if s in arms[a]:
                arms[a][s] = arms[a][s][:n]
    return arms


def llm_stats(seed, arm="muse"):
    p = os.path.join(CMP, f"{arm}_seed{seed}_calls.jsonl")
    if not os.path.exists(p):
        return None
    c = [json.loads(l) for l in open(p)]
    lat = [x["latency_s"] for x in c if x["latency_s"]]
    u = [x["usage"] for x in c]
    return {"calls": len(c), "failed_calls": sum(1 for x in c if x["error"]),
            "fallback_scenarios": sum(x["fallback"] for x in c), "repairs": sum(x["repairs"] for x in c),
            "prompt_tokens": sum(x.get("prompt_tokens", 0) for x in u),
            "completion_tokens": sum(x.get("completion_tokens", 0) for x in u),
            "reasoning_tokens": sum((x.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) for x in u),
            "latency_mean_s": float(np.mean(lat)) if lat else None, "latency_p95_s": float(np.percentile(lat, 95)) if lat else None,
            "latency_total_s": float(np.sum(lat))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    arms = load_runs()
    cache_p = os.path.join(CMP, "minimized.jsonl")
    cache = {}
    if os.path.exists(cache_p):
        for l in open(cache_p):
            d = json.loads(l); cache[d["key"]] = d

    def stale(d, viol):
        # 2026-11-04 wheel_saturation fix: entries minimized under the legacy cumulative rule are only reused when the
        # (corrected) earliest violation is still their target and saturation played no role in them.
        if d.get("sat_rule") == "consecutive":
            return d["target"] != min(viol, key=viol.get)
        return (d["target"] != min(viol, key=viol.get) or SAT in d["violations"]
                or SAT in d.get("violations_no_policy", {}))
    jobs = {}
    for arm, seeds in arms.items():
        for s, rows in seeds.items():
            for r in rows:
                if r["violated"]:
                    k = phash(r["params"])
                    if k not in cache or stale(cache[k], r["violations"]):
                        jobs[k] = (k, r["params"], r["violations"])
    print(f"minimizing {len(jobs)} violating runs ({len(cache)} cached)", flush=True)
    with open(cache_p, "a") as f, Pool(a.workers) as pool:
        for i, d in enumerate(pool.imap_unordered(_minimize, list(jobs.values()))):
            cache[d["key"]] = d; f.write(json.dumps(d) + "\n"); f.flush()
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(jobs)}", flush=True)

    summary = {"arms": {}, "patterns": {}}
    curves = {}
    allpat = {}
    for arm, seeds in sorted(arms.items()):
        per = {}
        for s, rows in sorted(seeds.items()):
            v = [r for r in rows if r["violated"]]
            first = next((i + 1 for i, r in enumerate(rows) if r["violated"]), None)
            seen_c, seen_f, seen_pi, seen_pis, cv, cu, cpi = set(), set(), set(), set(), [], [], []
            n_v = 0
            for r in rows:
                if r["violated"]:
                    n_v += 1
                    m = cache[phash(r["params"])]
                    if m["reproduces"]:
                        seen_c.add(m["pattern_coarse"]); seen_f.add(m["pattern_fine"])
                        if m["policy_induced"]:
                            seen_pi.add(m["pattern_fine"])
                            if not out_of_scope(m):
                                seen_pis.add(m["pattern_fine"])
                        allpat.setdefault(m["pattern_fine"], {}).setdefault(arm, []).append(
                            {"seed": s, "id": r["id"], "key": m["key"], "policy_induced": m["policy_induced"]})
                cv.append(n_v); cu.append(len(seen_f)); cpi.append(len(seen_pi))
            curves.setdefault(arm, {})[s] = (cv, cu, cpi)
            types = {}
            for r in v:
                for t in r["violations"]:
                    types[t] = types.get(t, 0) + 1
            mins = [cache[phash(r["params"])] for r in v]
            rep = [m for m in mins if m["reproduces"]]
            n_oos = sum(out_of_scope(m) for m in rep)
            per[s] = {"sims": len(rows), "violations": len(v), "violations_per_sim": len(v) / len(rows),
                      "sims_to_first_violation": first, "unique_patterns_coarse": len(seen_c),
                      "unique_patterns_fine": len(seen_f), "unique_patterns_policy_induced": len(seen_pi),
                      "patterns_policy_induced": sorted(seen_pi), "violation_types": types,
                      "policy_induced_minimized": sum(m["policy_induced"] for m in mins),
                      "minimized_non_reproducing": sum(not m["reproduces"] for m in mins),
                      "minimization_sims": sum(m["minimization_sims"] for m in mins),
                      "unique_patterns_policy_induced_in_scope": len(seen_pis),
                      "out_of_scope_minimized": n_oos, "out_of_scope_share": n_oos / len(rep) if rep else None,
                      "policy_induced_in_scope_minimized": sum(m["policy_induced"] and not out_of_scope(m) for m in rep),
                      "patterns_fine": sorted(seen_f)}
            if arm.startswith("muse"):
                per[s]["llm"] = llm_stats(s, arm)
        keys = ["violations_per_sim", "sims_to_first_violation", "unique_patterns_coarse", "unique_patterns_fine",
                "unique_patterns_policy_induced", "unique_patterns_policy_induced_in_scope", "out_of_scope_share"]
        mean = {k: float(np.nanmean([p[k] if p[k] is not None else np.nan for p in per.values()])) for k in keys}
        mean["seeds"] = sorted(per)
        std = {k: float(np.nanstd([p[k] if p[k] is not None else np.nan for p in per.values()])) for k in keys}
        union_f = sorted(set().union(*[set(p["patterns_fine"]) for p in per.values()]))
        union_pi = sorted(set().union(*[set(p["patterns_policy_induced"]) for p in per.values()]))
        summary["arms"][arm] = {"per_seed": per, "mean": mean, "std": std, "union_patterns_fine": union_f,
                                "union_patterns_policy_induced": union_pi}
    summary["patterns"] = allpat
    unions = {n: set(d["union_patterns_fine"]) for n, d in summary["arms"].items()}
    unions_pi = {n: set(d["union_patterns_policy_induced"]) for n, d in summary["arms"].items()}
    summary["only_in_arm"] = {n: sorted(u - set().union(*[v for m, v in unions.items() if m != n])) for n, u in unions.items()}
    summary["only_in_arm_policy_induced"] = {n: sorted(u - set().union(*[v for m, v in unions_pi.items() if m != n]))
                                             for n, u in unions_pi.items()}
    # head-to-head on the seeds every arm ran (rules-blind Muse ran seed 1 only)
    common = sorted(set.intersection(*[set(d["per_seed"]) for d in summary["arms"].values()]))
    summary["common_seeds"] = common
    summary["head_to_head"] = {n: {s: {k: d["per_seed"][s][k] for k in keys} for s in common}
                               for n, d in summary["arms"].items()}
    json.dump(summary, open(os.path.join(CMP, "summary.json"), "w"), indent=1)

    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    # lead with coarse patterns (distinct failure mechanisms by fault kind); bars = mean over seeds, dots = seeds
    col = {"muse": "tab:blue", "museblind": "tab:purple", "cmaes": "tab:red", "random": "tab:gray"}
    nice = {"muse": "Muse", "museblind": "Muse-blind", "cmaes": "CMA-ES", "random": "random"}
    names = [n for n in ("muse", "museblind", "cmaes", "random") if n in summary["arms"]]
    panels = [("unique_patterns_coarse", "Unique failure patterns, COARSE\n(violation <- fault kinds)", False),
              ("unique_patterns_fine", "Unique failure patterns, fine\n(wheel / leak axis)", False),
              ("violations_per_sim", "Violations per simulation", False),
              ("sims_to_first_violation", "Sims to first violation (lower = better)", True)]
    fig, ax = plt.subplots(1, 4, figsize=(18, 4.6))
    xx = np.arange(len(names))
    for a_, (k, title, _) in zip(ax, panels):
        mu = [summary["arms"][n]["mean"][k] for n in names]
        a_.bar(xx, mu, 0.6, color=[col[n] for n in names], alpha=0.85)
        for x_, n in zip(xx, names):
            vals = [p[k] for p in summary["arms"][n]["per_seed"].values() if p[k] is not None]
            a_.scatter([x_] * len(vals), vals, color="k", s=14, zorder=3)
        for x_, m_ in zip(xx, mu):
            a_.text(x_, m_, f"{m_:.2f}" if k == "violations_per_sim" else f"{m_:.1f}", ha="center", va="bottom", fontsize=9)
        a_.set_xticks(xx, [f"{nice[n]}\n({len(summary['arms'][n]['per_seed'])} seeds)" for n in names], fontsize=9)
        a_.set_title(title, fontsize=10); a_.grid(alpha=0.3, axis="y")
    fig.suptitle("Equal sim budget per seed (" + ", ".join(f"seed {s}: {len(arms[names[0]][s])} sims" for s in sorted(arms[names[0]])) + "). "
                 "Bars = mean over seeds, dots = individual seeds", fontsize=10)
    fig.tight_layout()
    out = os.path.join(ROOT, "plots", "arms_comparison.png"); fig.savefig(out, dpi=130)
    print("wrote", out)
    for n in names:
        print(n, json.dumps(summary["arms"][n]["mean"]))
    print("head_to_head seeds", common)
    for n in names:
        print(" ", n, json.dumps(summary["head_to_head"][n]))
    for n in names:
        print("only in", n, len(summary["only_in_arm"][n]), "policy-induced:", summary["only_in_arm_policy_induced"][n])


if __name__ == "__main__":
    main()
