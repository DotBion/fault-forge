"""Apples-to-apples arms comparison under the CORRECTED (consecutive > 60 s) wheel_saturation rule.

  python3 src/matched_compare.py --workers 3

Arms: muse, museblind, cmaes, random (stored in data/cmp/, scored with the old cumulative rule) plus the matched
arms in data/matched/<arm>_seed<s>.jsonl (matchfam, matchall, oneshot if present; already run with the fix).

Re-scoring the stored arms: the fix can only REMOVE wheel_saturation (consecutive time <= cumulative time) and
saturation bookkeeping does not feed back into the policy, so only stored runs whose violations include
wheel_saturation can change. Those are re-simulated (same params, same policy v1) and replaced
(data/matched/rescored_<arm>_seed<s>.jsonl holds the re-simulated rows; resumable cache).
Minimization: every violating run is minimized against its earliest violation (same code as src/compare.py).
Entries of data/cmp/minimized.jsonl whose target is NOT wheel_saturation are rule-independent and reused;
everything else is recomputed into data/matched/minimized_satfix.jsonl.
Equal budget per seed: all arms truncated to the shortest arm for that seed (seed 0: 232, seeds 1-2: 300).

writes data/matched/summary.json, plots/arms_comparison_matched.png
"""
import argparse
import glob
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare as C  # noqa: E402
import ff_sim  # noqa: E402
from matched_search import satfix_landed  # noqa: E402

ROOT = C.ROOT
CMP, MD = C.CMP, os.path.join(ROOT, "data", "matched")
OLD_ARMS = ["muse", "museblind", "cmaes", "random"]
NEW_ARMS = ["matchfam", "matchall", "oneshot"]


def _resim(job):
    key, params = job
    r = ff_sim.run_scenario(params, telemetry=False)
    r.pop("policy_log", None)
    return key, r


def read_jsonl(p):
    out = []
    if os.path.exists(p):
        for l in open(p):
            if l.strip().endswith("}"):
                out.append(json.loads(l))
    return out


def load_all(workers):
    arms = {}
    for arm in OLD_ARMS:
        for s in (0, 1, 2):
            p = os.path.join(CMP, f"{arm}_seed{s}.jsonl")
            if os.path.exists(p):
                arms.setdefault(arm, {})[s] = sorted(read_jsonl(p), key=lambda r: r["id"])
    for arm in NEW_ARMS:
        for p in sorted(glob.glob(os.path.join(MD, f"{arm}_seed[0-9].jsonl"))):
            s = int(p[-7])
            arms.setdefault(arm, {})[s] = sorted(read_jsonl(p), key=lambda r: r["id"])
    # re-simulate stored rows that carry wheel_saturation under the old rule
    stats = {}
    jobs = []
    for arm in OLD_ARMS:
        for s, rows in arms.get(arm, {}).items():
            cp = os.path.join(MD, f"rescored_{arm}_seed{s}.jsonl")
            cache = {d["id"]: d for d in read_jsonl(cp)}
            for r in rows:
                if "wheel_saturation" in r["violations"] and r["id"] not in cache:
                    jobs.append(((arm, s, r["id"]), r["params"]))
    print(f"re-simulating {len(jobs)} stored runs that had wheel_saturation", flush=True)
    if jobs:
        fh = {}
        with Pool(workers) as pool:
            for k, ((arm, s, rid), res) in enumerate(pool.imap_unordered(_resim, jobs)):
                f = fh.setdefault((arm, s), open(os.path.join(MD, f"rescored_{arm}_seed{s}.jsonl"), "a"))
                f.write(json.dumps({"id": rid, **res}) + "\n"); f.flush()
                if (k + 1) % 25 == 0:
                    print(f"  resim {k+1}/{len(jobs)}", flush=True)
        for f in fh.values():
            f.close()
    for arm in OLD_ARMS:
        for s, rows in arms.get(arm, {}).items():
            cache = {d["id"]: d for d in read_jsonl(os.path.join(MD, f"rescored_{arm}_seed{s}.jsonl"))}
            st = stats.setdefault(arm, {}).setdefault(s, {"had_wheel_sat": 0, "lost_wheel_sat": 0,
                                                          "flipped_to_clean": 0, "violations_old": 0})
            new = []
            for r in rows:
                st["violations_old"] += r["violated"]
                if "wheel_saturation" in r["violations"]:
                    c = cache[r["id"]]
                    st["had_wheel_sat"] += 1
                    st["lost_wheel_sat"] += "wheel_saturation" not in c["violations"]
                    st["flipped_to_clean"] += not c["violated"]
                    # sanity: the rule fix must not change the other constraints
                    for t in ("attitude_loss", "battery_floor"):
                        assert (t in r["violations"]) == (t in c["violations"]), (arm, s, r["id"], t)
                    r = {**r, **{k: c[k] for k in ("violations", "violated", "margins", "sim_time_s")}, "rescored": True}
                new.append(r)
            arms[arm][s] = new
    for s in set().union(*[set(v) for v in arms.values()]):
        n = min(len(arms[a][s]) for a in arms if s in arms[a])
        for a in arms:
            if s in arms[a]:
                arms[a][s] = arms[a][s][:n]
    return arms, stats


def target_of(viol):
    return min(viol, key=viol.get)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if not satfix_landed():
        sys.exit("ff_sim.py still has the cumulative wheel_saturation rule; refusing to run")
    arms, rescore_stats = load_all(a.workers)
    old = {d["key"]: d for d in read_jsonl(os.path.join(CMP, "minimized.jsonl"))}
    cp = os.path.join(MD, "minimized_satfix.jsonl")
    cache = {d["key"]: d for d in read_jsonl(cp)}
    jobs = {}
    for arm, seeds in arms.items():
        for s, rows in seeds.items():
            for r in rows:
                if not r["violated"]:
                    continue
                k = C.phash(r["params"]); t = target_of(r["violations"])
                if k in cache and cache[k]["target"] == t:
                    continue
                if k in old and old[k]["target"] == t and t != "wheel_saturation":
                    cache[k] = {**old[k], "reused_from_cmp": True}; continue
                jobs[k] = (k, r["params"], r["violations"])
    print(f"minimizing {len(jobs)} violating runs ({len(cache)} cached/reused)", flush=True)
    with open(cp, "w") as f:
        for d in cache.values():
            f.write(json.dumps(d) + "\n")
    with open(cp, "a") as f, Pool(a.workers) as pool:
        for i, d in enumerate(pool.imap_unordered(C._minimize, list(jobs.values()))):
            cache[d["key"]] = d; f.write(json.dumps(d) + "\n"); f.flush()
            if (i + 1) % 10 == 0:
                print(f"  min {i+1}/{len(jobs)}", flush=True)

    keys = ["violations_per_sim", "sims_to_first_violation", "unique_patterns_coarse", "unique_patterns_fine",
            "unique_patterns_policy_induced", "unique_patterns_policy_induced_in_scope"]
    summary = {"rule": "wheel_saturation = one wheel >= 98% speed for > 60 s CONSECUTIVE (fixed)",
               "budget_per_seed": {s: len(arms["random"][s]) for s in sorted(arms["random"])},
               "rescore_of_stored_arms": rescore_stats, "arms": {}}
    for arm, seeds in arms.items():
        per = {}
        for s, rows in sorted(seeds.items()):
            v = [r for r in rows if r["violated"]]
            first = next((i + 1 for i, r in enumerate(rows) if r["violated"]), None)
            sc, sf, spi, spis = set(), set(), set(), set()
            types = {}
            for r in v:
                for t in r["violations"]:
                    types[t] = types.get(t, 0) + 1
                m = cache[C.phash(r["params"])]
                if m["reproduces"]:
                    sc.add(m["pattern_coarse"]); sf.add(m["pattern_fine"])
                    if m["policy_induced"]:
                        spi.add(m["pattern_fine"])
                        if not C.out_of_scope(m):
                            spis.add(m["pattern_fine"])
            per[s] = {"sims": len(rows), "violations": len(v), "violations_per_sim": len(v) / len(rows),
                      "sims_to_first_violation": first, "unique_patterns_coarse": len(sc),
                      "unique_patterns_fine": len(sf), "unique_patterns_policy_induced": len(spi),
                      "unique_patterns_policy_induced_in_scope": len(spis), "violation_types": types,
                      "patterns_coarse": sorted(sc), "patterns_fine": sorted(sf)}
        mean = {k: float(np.nanmean([p[k] if p[k] is not None else np.nan for p in per.values()])) for k in keys}
        std = {k: float(np.nanstd([p[k] if p[k] is not None else np.nan for p in per.values()])) for k in keys}
        summary["arms"][arm] = {"per_seed": per, "mean": mean, "std": std,
                                "union_patterns_coarse": sorted(set().union(*[set(p["patterns_coarse"]) for p in per.values()])),
                                "union_patterns_fine": sorted(set().union(*[set(p["patterns_fine"]) for p in per.values()]))}
    summary["minimization_cache"] = {"entries": len(cache), "reused_from_cmp": sum(1 for d in cache.values() if d.get("reused_from_cmp"))}
    json.dump(summary, open(os.path.join(MD, "summary.json"), "w"), indent=1)

    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    col = {"muse": "tab:blue", "museblind": "tab:purple", "oneshot": "tab:cyan", "matchall": "tab:green",
           "matchfam": "tab:olive", "cmaes": "tab:red", "random": "tab:gray"}
    nice = {"muse": "Muse", "museblind": "Muse-blind", "oneshot": "1-shot Muse\n+mutation", "matchall": "matched\nfam+marg.",
            "matchfam": "matched\nfamily", "cmaes": "CMA-ES", "random": "random"}
    names = [n for n in ("muse", "museblind", "oneshot", "matchall", "matchfam", "cmaes", "random") if n in summary["arms"]]
    panels = [("unique_patterns_coarse", "Distinct fault-combination signatures\n(coarse: violation <- fault kinds)"),
              ("unique_patterns_fine", "Fine patterns\n(wheel index / leak axis)"),
              ("violations_per_sim", "Violations per simulation"),
              ("sims_to_first_violation", "Sims to first violation (lower = better)")]
    fig, ax = plt.subplots(1, 4, figsize=(22, 5))
    xx = np.arange(len(names))
    for a_, (k, title) in zip(ax, panels):
        mu = [summary["arms"][n]["mean"][k] for n in names]
        a_.bar(xx, mu, 0.65, color=[col[n] for n in names], alpha=0.85)
        for x_, n in zip(xx, names):
            vals = [p[k] for p in summary["arms"][n]["per_seed"].values() if p[k] is not None]
            a_.scatter([x_] * len(vals), vals, color="k", s=14, zorder=3)
            if k == "sims_to_first_violation":
                miss = sum(p[k] is None for p in summary["arms"][n]["per_seed"].values())
                if miss:
                    a_.text(x_, 0, f"{miss} seed(s)\nnone", ha="center", va="bottom", fontsize=7)
        for x_, m_ in zip(xx, mu):
            if np.isfinite(m_):
                a_.text(x_, m_, f"{m_:.2f}" if k == "violations_per_sim" else f"{m_:.1f}", ha="center", va="bottom", fontsize=9)
        a_.set_xticks(xx, [nice[n] for n in names], fontsize=8)
        a_.set_title(title, fontsize=10); a_.grid(alpha=0.3, axis="y")
    b = summary["budget_per_seed"]
    fig.suptitle("Corrected wheel_saturation rule (consecutive > 60 s). Equal sim budget per seed ("
                 + ", ".join(f"seed {s}: {n}" for s, n in b.items()) + "); bars = mean of 3 seeds, dots = seeds. "
                 "Matched arms: open-loop random drawn from Muse's empirical proposal distribution", fontsize=10)
    fig.tight_layout()
    out = os.path.join(ROOT, "plots", "arms_comparison_matched.png"); fig.savefig(out, dpi=130)
    print("wrote", out)
    print("rescore", json.dumps(rescore_stats))
    for n in names:
        print(f"{n:10s}", json.dumps({k: round(v, 3) for k, v in summary["arms"][n]["mean"].items()}),
              "per-seed v/sim", [round(p["violations_per_sim"], 3) for p in summary["arms"][n]["per_seed"].values()])


if __name__ == "__main__":
    main()
