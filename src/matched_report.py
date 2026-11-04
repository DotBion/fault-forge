"""Render data/matched/report.md from data/matched/summary.json + data/matched/muse_distribution.json.
  python3 src/matched_report.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "data", "matched")
NICE = {"muse": "Muse-guided (closed loop)", "museblind": "Muse rules-blind (closed loop)",
        "oneshot": "One-shot Muse bank (40) + random mutations", "matchall": "Matched random: family + marginals",
        "matchfam": "Matched random: family only", "cmaes": "CMA-ES (closed loop)", "random": "Plain random"}
ORDER = ["muse", "museblind", "oneshot", "matchall", "matchfam", "cmaes", "random"]


def fmt(arm, k, d):
    per = [d["per_seed"][s][k] for s in sorted(d["per_seed"])]
    m = d["mean"][k]
    f = (lambda x: "-" if x is None else f"{x:.3f}") if k == "violations_per_sim" else (lambda x: "none" if x is None else f"{x:g}")
    ms = "n/a" if m != m else (f"{m:.3f}" if k == "violations_per_sim" else f"{m:.1f}")
    return f"{ms} ({' / '.join(f(x) for x in per)})"


def main():
    S = json.load(open(os.path.join(MD, "summary.json")))
    D = json.load(open(os.path.join(MD, "muse_distribution.json")))
    m, r = D["muse_all_seeds"], D["random_all_seeds"]
    arms = [a for a in ORDER if a in S["arms"]]
    L = ["# Is Muse just picking the right fault family? Matched-random baselines",
         "",
         f"All arms scored with the **corrected wheel_saturation rule** (consecutive > 60 s; fix c09fbf5, impact in "
         f"`data/satfix/impact.md`). Equal sim budget per seed ({', '.join(f'seed {s}: {n}' for s, n in S['budget_per_seed'].items())}"
         "), 3 seeds per arm, same simulator, policy v1, same minimization + pattern code (`src/compare.py` functions).",
         "Cells: **mean over 3 seeds** (seed 0 / seed 1 / seed 2).", "",
         "| arm | violations / sim | distinct fault-combination signatures (coarse) | fine patterns | policy-induced fine patterns (in scope) | sims to first violation |",
         "|---|---|---|---|---|---|"]
    for a in arms:
        d = S["arms"][a]
        L.append(f"| {NICE[a]} | {fmt(a, 'violations_per_sim', d)} | {fmt(a, 'unique_patterns_coarse', d)} | "
                 f"{fmt(a, 'unique_patterns_fine', d)} | {fmt(a, 'unique_patterns_policy_induced_in_scope', d)} | "
                 f"{fmt(a, 'sims_to_first_violation', d)} |")
    L += ["", "Union over 3 seeds (distinct coarse signatures / fine patterns):", ""]
    for a in arms:
        d = S["arms"][a]
        L.append(f"- {NICE[a]}: {len(d['union_patterns_coarse'])} / {len(d['union_patterns_fine'])}")
    L += ["", "## Muse's empirical proposal distribution (784 Muse proposals, 3 seeds; 48 random fallbacks excluded)", "",
          "| | Muse | plain random |", "|---|---|---|",
          f"| two-wheel fault scenarios | {m['two_wheel_fraction']:.1%} | {r['two_wheel_fraction']:.1%} |",
          f"| RW fault count 0 / 1 / 2 | {' / '.join(f'{v:.0%}' for v in m['rw_fault_count'].values())} | {' / '.join(f'{v:.0%}' for v in r['rw_fault_count'].values())} |",
          f"| heater / leak present | {m['heater_fraction']:.0%} / {m['leak_fraction']:.0%} | {r['heater_fraction']:.0%} / {r['leak_fraction']:.0%} |",
          f"| RW severity = 1.0 (derate / friction) | {m['rw_severity_at_1.0_share']['torque_derate']:.0%} / {m['rw_severity_at_1.0_share']['friction']:.0%} | ~0% (uniform 0.2-1.0) |",
          f"| median RW onset (fraction of run) | {m['rw_onset_frac']['p05_25_50_75_95'][2]:.3f} | 0.40 (uniform 0-0.8) |",
          f"| median beta (deg) | {m['beta_deg']['p05_25_50_75_95'][2]:.0f} | 35 (uniform 0-70) |",
          f"| median heater W / leak Nm | {m['heater_power_W']['p05_25_50_75_95'][2]:.1f} / {m['leak_mag_Nm']['p05_25_50_75_95'][2]:.1e} | 3.5 / 9e-7 |",
          "", "Full distribution: `data/matched/muse_distribution.json` (`python3 src/muse_distribution.py`).", "",
          "## Arms", "",
          "- **Matched random: family only** (`matchfam`): fault-kind combination (RW fault count + types, heater y/n, leak y/n) drawn from Muse's empirical joint combo distribution; wheel indices uniform; every continuous parameter uniform exactly as plain random. Open loop.",
          "- **Matched random: family + marginals** (`matchall`): as above, but each continuous parameter is drawn independently from Muse's pooled empirical marginal (bootstrap of observed values). Open loop. These marginals are what Muse converged to *with* feedback, so this is an optimistic, hindsight-informed baseline: it only exists because Muse was run first.",
          "- **One-shot Muse bank** (`oneshot`): one Muse call per seed (same system prompt as the Muse arm, no results ever shown) returns 40 scenarios; the remaining budget is plain random mutations of uniformly chosen bank members, no selection on outcomes. Provenance (model, response id, request id) in `data/matched/oneshot_seed*_bank.json`.",
          "- Muse / Muse-blind / CMA-ES / plain random: stored runs in `data/cmp/`, re-scored under the corrected rule (rows rewritten by `src/satfix.py`; `src/matched_compare.py` re-simulated every row still carrying wheel_saturation as a cross-check and asserts attitude/battery outcomes are unchanged).",
          "", "Coarse signature = earliest violation <- sorted fault kinds of the delta-debugged minimal counterexample; fine adds wheel index / leak axis. Counted only for minimized cases that reproduce.", ""]
    oneshot = []
    for s in (0, 1, 2):
        p = os.path.join(MD, f"oneshot_seed{s}_bank.json")
        if os.path.exists(p):
            b = json.load(open(p)); pv = b["provenance"]
            oneshot.append(f"- seed {s}: {b['valid']}/{b['requested']} valid; model `{pv.get('model')}`, response_id `{pv.get('response_id')}`, request_id `{pv.get('request_id')}`, {pv.get('latency_s')} s")
    if oneshot:
        L += ["One-shot bank calls:", ""] + oneshot + [""]
    L += ["## Reproduce", "", "```", "python3 src/muse_distribution.py",
          "bash data/matched/run_matched_chain.sh   # matchfam, matchall, oneshot (bank needs MUSE_API_KEY), then matched_compare",
          "python3 src/matched_report.py", "```", "", "## Reading", "", "READING_PLACEHOLDER", ""]
    open(os.path.join(MD, "report.md"), "w").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
