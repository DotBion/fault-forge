"""Regression-gated policy repair loop (Muse proposes, the full verification suite decides).

  python src/gated_repair.py heldout            # fixed held-out set: Muse search on v1 (seed 100, 100 sims) + 200 random
  python src/gated_repair.py loop --rounds 3    # rounds of propose -> gate, up to --tries proposals per round
  python src/gated_repair.py fresh              # fresh Muse search (seed 100, 100 sims) vs the final accepted policy
  python src/gated_repair.py report             # data/gated/summary.json + plots/gated_repair_trend.png

Gate (per proposal), on the FULL suite = 576 single-fault grid (incl. nominal) + the 2,932 stored v1 search runs
(data/cmp, the snapshot listed in SUITE_FILES):
  accept  iff  new_violations == 0  and  fixes > 0, both relative to the CURRENT accepted policy, where
  new_violations = (run, violation type) pairs the candidate has and the current policy does not have,
  fixes          = runs that violate under the current policy and are clean under the candidate.
A proposal is evaluated in order (previous regressions first, then grid, then the rest); evaluation stops early once
EARLY_ABORT new violations are found (it is rejected anyway, and the regressions found are fed back to Muse).
On rejection Muse gets the regressions (with policy traces under both policies) and retries, up to --tries per round.

Everything is resumable from data/gated/ (each artefact is written once; evaluations append per run).
"""
import argparse
import glob
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
import repair as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMP = os.path.join(ROOT, "data", "cmp")
G = os.path.join(ROOT, "data", "gated")
os.makedirs(G, exist_ok=True)
SUITE_FILES = [f"{a}_seed{s}.jsonl" for a in ("cmaes", "muse", "random") for s in (0, 1, 2)] + ["museblind_seed1.jsonl"]
EARLY_ABORT = 20  # default; the loop now uses --abort (3 since the restart, see README_gated note)
HELDOUT_SEED, HELDOUT_MUSE, HELDOUT_RANDOM = 100, 100, 200


def jl(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def pol_path(name):
    return os.path.join(G, f"policy_{name}.json")


def get_pol(name):
    return ff_sim.POLICY if name == "v1" else ff_sim.get_policy(pol_path(name))


# ------------------------------------------------------------------ suite
def load_suite():
    """id -> params, and v1 violations (v1 is deterministic; grid v1 from the stored v1-vs-v2 regression file)."""
    from search import grid_jobs
    params, v1 = {}, {}
    for i, _, p in grid_jobs():
        params[f"grid_{i}"] = p
    for fn in SUITE_FILES:
        arm = fn[:-6]
        for r in jl(os.path.join(CMP, fn)):
            params[f"{arm}_{r['id']}"] = r["params"]; v1[f"{arm}_{r['id']}"] = r["violations"]
    for r in jl(os.path.join(ROOT, "data", "repair", "regress_v2.jsonl")):
        if r["id"].startswith("grid_"):
            v1[r["id"]] = r["v1"]
    assert len(params) == 3508 and set(params) == set(v1), (len(params), len(v1))
    return params, v1


def _job(job):
    key, params, polname = job
    r = ff_sim.run_scenario(params, telemetry=False, policy=get_pol(polname))
    return key, r["violations"]


def evaluate(polname, items, out_path, workers, base=None, abort=None):
    """Run (key, params) items under polname, appending {id, violations} to out_path (resumable).
    If base/abort given, stop once >= abort new (run, type) violations vs base are seen. Returns (dict, complete)."""
    done = {r["id"]: r["violations"] for r in jl(out_path)}
    todo = [(k, p, polname) for k, p in items if k not in done]

    def n_new():
        return sum(len(set(v) - set(base.get(k, {}))) for k, v in done.items()) if base is not None else 0
    if abort and n_new() >= abort:
        return done, False
    t0 = time.time()
    with open(out_path, "a") as f, Pool(workers) as pool:
        for i, (k, v) in enumerate(pool.imap(_job, todo, chunksize=2)):
            done[k] = v; f.write(json.dumps({"id": k, "violations": v}) + "\n"); f.flush()
            if (i + 1) % 250 == 0:
                print(f"    {polname}: {i+1}/{len(todo)} {time.time()-t0:.0f}s, new viol so far {n_new()}", flush=True)
            if abort and base is not None and v and set(v) - set(base.get(k, {})) and n_new() >= abort:
                pool.terminate()
                return done, False
    return done, len(done) >= len(items)


def compare(base, cand, keys):
    new = [(k, t) for k in keys if k in cand for t in set(cand[k]) - set(base[k])]
    fixes = [k for k in keys if k in cand and base[k] and not cand[k]]
    reg_runs = sorted({k for k, _ in new})
    return {"evaluated": sum(k in cand for k in keys), "new_violations": len(new), "runs_with_new_violations": len(reg_runs),
            "clean_to_violating": sum(1 for k in reg_runs if not base[k]), "fixes": len(fixes),
            "violating_runs": sum(bool(cand[k]) for k in keys if k in cand),
            "violating_runs_base": sum(bool(base[k]) for k in keys if k in cand),
            "new_violation_ids": reg_runs, "fix_ids": fixes}


# ------------------------------------------------------------------ held-out set
def heldout_items():
    from search import sample_params
    muse = jl(os.path.join(G, f"heldout_muse_seed{HELDOUT_SEED}.jsonl"))
    rng = np.random.default_rng(424242)
    items = [(f"hmuse_{r['id']}", r["params"]) for r in muse]
    items += [(f"hrand_{i}", sample_params(rng)) for i in range(HELDOUT_RANDOM)]
    return items


def cmd_heldout(a):
    import subprocess
    out = os.path.join(G, f"heldout_muse_seed{HELDOUT_SEED}.jsonl")
    if len(jl(out)) < HELDOUT_MUSE:
        cmd = [sys.executable, os.path.join(ROOT, "src", "llm_search.py"), "--seed", str(HELDOUT_SEED), "--budget",
               str(HELDOUT_MUSE), "--workers", str(a.workers), "--out", out] + (["--resume"] if os.path.exists(out) else [])
        subprocess.run(cmd, check=True)
    items = heldout_items()
    d, ok = evaluate("v1", items, os.path.join(G, "heldout_eval_v1.jsonl"), a.workers)
    print("held-out v1:", sum(bool(v) for v in d.values()), "/", len(d))


def heldout_rate(polname, workers):
    items = heldout_items()
    d, _ = evaluate(polname, items, os.path.join(G, f"heldout_eval_{polname}.jsonl"), workers)
    m = [k for k, _ in items if k.startswith("hmuse")]; rr = [k for k, _ in items if k.startswith("hrand")]
    f = lambda ks: {"n": len(ks), "violating": sum(bool(d[k]) for k in ks), "rate": sum(bool(d[k]) for k in ks) / len(ks)}
    return {"all": f(m + rr), "muse": f(m), "random": f(rr)}


# ------------------------------------------------------------------ proposals
def failing_cases(polname, workers):
    """v1 in-scope policy-induced minimized counterexamples that still fail (target violated) under polname."""
    mins = [d for d in R.load_minimized() if d["policy_induced"] and not R.out_of_scope(d["minimized"])]
    if polname == "v1":
        return mins
    d, _ = evaluate(polname, [(m["key"], m["minimized"]) for m in mins], os.path.join(G, f"mins_eval_{polname}.jsonl"), workers)
    return [m for m in mins if m["target"] in d[m["key"]]]


def _trace(job):
    params, polname = job
    return R.trace(params, get_pol(polname))


def sig(p):
    """fault-kind signature of a scenario, e.g. 'leak+rw0_friction+rw1_torque_derate'."""
    parts = (["heater"] if p.get("heater") else []) + (["leak"] if p.get("torque_leak") else [])
    parts += sorted(f"rw{f['wheel']}_{f['type']}" for f in p.get("rw_faults") or [])
    return "+".join(parts) or "nominal"


def faults_of(p):
    return {k: p[k] for k in ("orbit", "rw_faults", "heater", "torque_leak")}


SYS = ("You are a spacecraft fault-protection engineer. Simulation-based verification found multi-fault cases in which the "
       "onboard safe-mode/FDIR policy itself causes a safety violation that would not occur with the policy disabled. "
       "Propose ONE small, concrete policy change, chosen only from the whitelist, that removes some of these failure cases. "
       "Hard acceptance gate: the change is tested on a regression suite of 3,508 runs (576 single-fault + nominal runs and "
       "2,932 multi-fault runs) and is REJECTED if it introduces even one new violation relative to the current policy. "
       "Prefer narrow, conservative changes that fix fewer cases with zero side effects over broad ones. "
       + "Write in plain reliability-engineering wording.")


def build_prompt(rnd, tri, cur, cases, attempts, accepted_hist, workers, base_tries=99):
    import llm_search as L
    P = get_pol(cur)
    stats = {}
    for d in cases:
        stats[d["pattern_coarse"]] = stats.get(d["pattern_coarse"], 0) + 1
    reps = R.pick_cases(cases, 8)
    jobs = [(d["minimized"], cur) for d in reps]
    reg_jobs = []
    if attempts:
        last = attempts[-1]
        ids = last["gate"]["new_violation_ids"]
        pick = ids[:: max(1, len(ids) // 5)][:5]
        reg_jobs = [(k, last["name"]) for k in pick]
    with Pool(workers) as pool:
        tr = pool.map(_trace, jobs)
        params, _ = load_suite()
        rtr_c = pool.map(_trace, [(params[k], n) for k, n in reg_jobs])
        rtr_b = pool.map(_trace, [(params[k], cur) for k, _ in reg_jobs])
    ex = [{"faults": faults_of(d["minimized"]), "with_current_policy": t, "without_policy_violations": d["violations_no_policy"]}
          for d, t in zip(reps, tr)]
    hist = ""
    if accepted_hist:
        hist = ("Changes accepted in earlier rounds (already part of the current policy): " + json.dumps(accepted_hist) + "\n")
    tried = ""
    if attempts:
        tried = "Proposals already REJECTED this round (do not repeat them):\n" + "\n".join(
            f"- try {x['try']}: change {json.dumps(x['change'])} -> {x['gate_reason']}" for x in attempts) + "\n"
        tried += ("Regressions caused by the last rejected proposal (runs where it adds a violation the current policy "
                  "does not have), with policy traces under both policies:\n" + json.dumps(
                      [{"faults": faults_of(params[k]), "with_rejected_proposal": c, "with_current_policy": b}
                       for (k, _), c, b in zip(reg_jobs, rtr_c, rtr_b)], separators=(',', ':')) + "\n")
    narrow = ""
    if tri > base_tries and attempts:
        from collections import Counter
        lines = []
        for x in attempts:
            g = x.get("gate", {})
            rc = Counter(sig(params[k]) for k in g.get("new_violation_ids", []))
            fc = Counter(sig(params[k]) for k in g.get("fix_ids", []))
            lines.append(f"- try {x['try']} {json.dumps(x['change'])}: {g.get('new_violations', 0)} new violations, "
                         f"{g.get('fixes', 0)} fixes (of {g.get('evaluated', 0)} runs evaluated). Regressed fault "
                         f"signatures: {json.dumps(dict(rc.most_common(12)))}; fixed signatures: {json.dumps(dict(fc.most_common(12)))}")
        narrow = ("No single change this round passed the zero-regression gate. For this proposal you may COMBINE "
                  "changes (up to the key limit) or NARROW one (e.g. keep isolation_swap but restrict it with "
                  "swap_min_res_Nm / swap_max_iso_res_Nm so it only acts on a clearly dead wheel replacing a mildly "
                  "degraded one) so that it keeps fixes while avoiding every regression listed below. Summary of all "
                  "rejected proposals (regression evaluation stops after a few new violations, so regression lists are "
                  "partial):\n" + "\n".join(lines) + "\n")
    user = L.PREFACE + f"""Round {rnd}, proposal {tri}.
Spacecraft: 6U CubeSat, 2-orbit sims, 4 reaction wheels, battery 30 Wh. Safety requirements: SoC >= 0.20; attitude
error <= 30 deg (not > 1200 s continuously after 900 s); no in-use wheel >= 98% max speed for > 60 s.
Fault types: torque_derate (u_max *= 1-severity), friction (Coulomb += severity*2 mNm), stuck heater, external torque leak.

{R.policy_text(P)}

{R.whitelist_text()}
At most {R.MAX_CHANGES} keys (swap_ratio / wheel_safe_s count only as tuning of their rule). Out of scope: cases with two
nearly dead wheels (already excluded).
{hist}{tried}{narrow}
Remaining in-scope policy-induced minimized failure cases under the current policy: {len(cases)}; count by pattern:
{json.dumps(stats)}
Representative cases (minimized; trace = policy actions, violations with times in s, near-miss margins):
{json.dumps(ex, separators=(',', ':'))}

Reply with ONLY a JSON object:
{{"diagnosis": str (<=120 words), "change": {{whitelist key: value, ...}}, "rationale": str (<=150 words),
 "why_no_regressions": str (<=80 words), "expected_fixed_patterns": [str]}}"""
    return user


def cmd_loop(a):
    import llm_search as L
    if not os.environ.get("MUSE_API_KEY"):
        sys.exit("MUSE_API_KEY not set")
    params, v1 = load_suite()
    keys = sorted(params)
    grid = [k for k in keys if k.startswith("grid_")]
    cur, base, accepted_hist = "v1", v1, []
    for rnd in range(1, a.rounds + 1):
        print(f"=== round {rnd} (current policy {cur})", flush=True)
        cases = failing_cases(cur, a.workers)
        attempts, acc = [], None
        for tri in range(1, a.tries + a.narrow_tries + 1):
            name = f"r{rnd}t{tri}"
            gp = os.path.join(G, f"{name}_gate.json")
            if os.path.exists(gp):
                x = json.load(open(gp)); attempts.append(x)
                print(f"  {name}: (cached) {x['decision']} {x['gate_reason']}", flush=True)
                if x["decision"] == "accept":
                    acc = x; break
                continue
            rp = os.path.join(G, f"{name}_response.json")
            if not os.path.exists(rp):
                user = build_prompt(rnd, tri, cur, cases, attempts, accepted_hist, a.workers, base_tries=a.tries)
                open(os.path.join(G, f"{name}_prompt.txt"), "w").write(SYS + "\n\n" + user)
                msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": user}]
                content, usage, lat, att = L.chat(msgs, seed=5000 + 10 * rnd + tri, max_tokens=16000)
                resp = json.loads(content)
                json.dump({"round": rnd, "try": tri, "model": L.MODEL, "latency_s": lat, "attempts": att, "usage": usage,
                           "n_cases": len(cases), "response_verbatim": content, "parsed": resp},
                          open(rp, "w"), indent=1)
            resp = json.load(open(rp))["parsed"]
            P = get_pol(cur)
            change, notes = R.validate_change(resp.get("change"), {k: P.get(k) for k in R.WHITELIST} | {
                k: P[k] for k in P if k != "name"})
            print(f"  {name}: Muse change {resp.get('change')} -> valid {change} {notes}", flush=True)
            rec = {"round": rnd, "try": tri, "name": name, "base": cur, "change_proposed": resp.get("change"),
                   "change": change, "validation_notes": notes, "diagnosis": resp.get("diagnosis"),
                   "rationale": resp.get("rationale"), "why_no_regressions": resp.get("why_no_regressions")}
            if not change:
                rec.update(decision="reject", gate_reason="no valid change (empty or identical to current policy)",
                           gate={"new_violation_ids": [], "fixes": 0, "new_violations": 0})
            else:
                newp = {k: v for k, v in P.items() if k != "name"} | change
                json.dump({"name": name, "base": cur, "params": newp, "change_vs_base": change}, open(pol_path(name), "w"), indent=1)
                prev_ids = [k for x in attempts for k in x["gate"]["new_violation_ids"]]
                order = list(dict.fromkeys(prev_ids + grid + keys))
                t0 = time.time()
                d, complete = evaluate(name, [(k, params[k]) for k in order], os.path.join(G, f"eval_{name}.jsonl"),
                                       a.workers, base=base, abort=a.abort)
                g = compare(base, d, keys)
                g["complete"] = complete; g["eval_s"] = round(time.time() - t0)
                if g["new_violations"] == 0 and complete and g["fixes"] > 0:
                    dec, why = "accept", f"accepted: 0 new violations, {g['fixes']} fixes on all {g['evaluated']} runs"
                elif g["new_violations"] == 0 and complete:
                    dec, why = "reject", "rejected: 0 new violations but 0 fixes"
                else:
                    dec = "reject"
                    why = (f"rejected: {g['new_violations']} new violations in {g['runs_with_new_violations']} runs "
                           f"({g['clean_to_violating']} previously clean) "
                           + ("(evaluation stopped early after " + str(g['evaluated']) + " runs)" if not complete else
                              f"vs {g['fixes']} fixes on the full suite"))
                rec.update(decision=dec, gate_reason=why, gate=g)
            json.dump(rec, open(gp, "w"), indent=1)
            print(f"  {name}: {rec['decision']} - {rec['gate_reason']}", flush=True)
            attempts.append(rec)
            if rec["decision"] == "accept":
                acc = rec; break
        if acc:
            cur = acc["name"]
            base = {r["id"]: r["violations"] for r in jl(os.path.join(G, f"eval_{cur}.jsonl"))}
            accepted_hist.append({"round": rnd, "change": acc["change"]})
        json.dump({"round": rnd, "accepted": acc["name"] if acc else None, "policy_after": cur,
                   "n_failing_cases_before": len(cases)}, open(os.path.join(G, f"round{rnd}.json"), "w"), indent=1)
        print(f"=== round {rnd}: {'accepted ' + acc['name'] if acc else 'nothing accepted'}; policy now {cur}", flush=True)


def cmd_fresh(a):
    import subprocess
    pol = a.policy or json.load(open(os.path.join(G, f"round{a.rounds}.json")))["policy_after"]
    out = os.path.join(G, f"fresh_muse_{pol}_seed{HELDOUT_SEED}.jsonl")
    if len(jl(out)) < HELDOUT_MUSE:
        cmd = [sys.executable, os.path.join(ROOT, "src", "llm_search.py"), "--seed", str(HELDOUT_SEED), "--budget",
               str(HELDOUT_MUSE), "--workers", str(a.workers), "--out", out, "--policy", pol_path(pol)] + (
            ["--resume"] if os.path.exists(out) else [])
        subprocess.run(cmd, check=True)
    rows = jl(out)
    print(pol, "fresh Muse search:", sum(r["violated"] for r in rows), "/", len(rows))


def cmd_report(a):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    params, v1 = load_suite(); keys = sorted(params)
    pols, log = ["v1"], []
    for rnd in range(1, a.rounds + 1):
        rp = os.path.join(G, f"round{rnd}.json")
        if not os.path.exists(rp):
            break
        x = json.load(open(rp)); pols.append(x["policy_after"])
        for gp in sorted(glob.glob(os.path.join(G, f"r{rnd}t*_gate.json"))):
            g = json.load(open(gp))
            log.append({k: g.get(k) for k in ("round", "try", "name", "base", "change_proposed", "change", "validation_notes",
                                              "decision", "gate_reason", "diagnosis", "rationale")} |
                       {"gate": {k: v for k, v in g["gate"].items() if not k.endswith("_ids")}})
    trend = []
    for i, p in enumerate(pols):
        d = v1 if p == "v1" else {r["id"]: r["violations"] for r in jl(os.path.join(G, f"eval_{p}.jsonl"))}
        h = heldout_rate(p, a.workers)
        trend.append({"label": "v1" if i == 0 else f"r{i}", "policy": p, "suite_violating_runs": sum(bool(d[k]) for k in keys),
                      "suite_violation_pairs": sum(len(d[k]) for k in keys), "suite_n": len(keys), "heldout": h,
                      "change_vs_v1": {k: v for k, v in get_pol(p).items() if k != "name" and ff_sim.POLICY.get(k) != v}})
    fresh = {}
    v1f = jl(os.path.join(G, f"heldout_muse_seed{HELDOUT_SEED}.jsonl"))
    fresh["v1"] = {"sims": len(v1f), "violations": sum(r["violated"] for r in v1f)}
    for fp in glob.glob(os.path.join(G, f"fresh_muse_*_seed{HELDOUT_SEED}.jsonl")):
        rows = jl(fp); p = os.path.basename(fp)[len("fresh_muse_"):-len(f"_seed{HELDOUT_SEED}.jsonl")]
        fresh[p] = {"sims": len(rows), "violations": sum(r["violated"] for r in rows)}
    for v in fresh.values():
        v["violations_per_sim"] = v["violations"] / max(v["sims"], 1)
    summ = {"gate": "accept iff 0 new (run, violation type) pairs vs current accepted policy AND >0 fixes, on 3,508 runs",
            "suite": "576 single-fault grid incl. 9 nominal + 2,932 stored v1 search runs (" + ", ".join(SUITE_FILES) + ")",
            "heldout": f"{HELDOUT_MUSE} Muse-generated scenarios (search on v1, seed {HELDOUT_SEED}) + {HELDOUT_RANDOM} random (rng 424242); disjoint from suite",
            "trend": trend, "attempts": log, "fresh_muse_search_seed100": fresh,
            "trend_down": all(trend[i + 1]["heldout"]["all"]["rate"] <= trend[i]["heldout"]["all"]["rate"] for i in range(len(trend) - 1))
                          and trend[-1]["heldout"]["all"]["rate"] < trend[0]["heldout"]["all"]["rate"]}
    json.dump(summ, open(os.path.join(G, "summary.json"), "w"), indent=1)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    lab = [t["label"] for t in trend]
    hr = [100 * t["heldout"]["all"]["rate"] for t in trend]
    hm = [100 * t["heldout"]["muse"]["rate"] for t in trend]
    hrr = [100 * t["heldout"]["random"]["rate"] for t in trend]
    ax.plot(lab, hr, "o-", lw=2.5, color="tab:blue", label=f"held-out, all {trend[0]['heldout']['all']['n']} scenarios")
    ax.plot(lab, hm, "s--", color="tab:purple", alpha=0.7, label=f"held-out, Muse-generated ({HELDOUT_MUSE})")
    ax.plot(lab, hrr, "^--", color="tab:gray", alpha=0.7, label=f"held-out, random ({HELDOUT_RANDOM})")
    for x, y in zip(lab, hr):
        ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    ax.set_ylabel("held-out violation rate (%)"); ax.set_ylim(bottom=0); ax.grid(alpha=0.3)
    ax2 = ax.twinx()
    ax2.bar(lab, [t["suite_violating_runs"] for t in trend], alpha=0.18, color="tab:red", width=0.5)
    for x, t in zip(lab, trend):
        ax2.text(x, t["suite_violating_runs"] * 0.5, f"{t['suite_violating_runs']}", ha="center", color="tab:red", fontsize=9)
    ax2.set_ylabel("violating runs on 3,508-run regression suite (bars)", color="tab:red"); ax2.set_ylim(bottom=0)
    ax.set_zorder(ax2.get_zorder() + 1); ax.patch.set_visible(False)
    ax.set_xlabel("accepted policy after each gated round (r1-r3); round with no accepted patch = unchanged")
    ax.set_title("Regression-gated repair loop: Muse proposes, 3,508-run suite gates (0 new violations allowed)", fontsize=10)
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout(); fp = os.path.join(ROOT, "plots", "gated_repair_trend.png"); fig.savefig(fp, dpi=140); print("wrote", fp)
    print(json.dumps({"trend": [{k: t[k] for k in ("label", "policy", "suite_violating_runs")} | {"heldout": t["heldout"]["all"]}
                                for t in trend], "fresh": fresh, "trend_down": summ["trend_down"]}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["heldout", "loop", "fresh", "report"])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--tries", type=int, default=4, help="proposals per round (1 + up to 3 retries)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--narrow-tries", type=int, default=2,
                    help="extra proposals when the regular tries fail: Muse may combine or narrow changes")
    ap.add_argument("--abort", type=int, default=3, help="stop a gate evaluation after this many new violations")
    ap.add_argument("--policy", default=None)
    a = ap.parse_args()
    {"heldout": cmd_heldout, "loop": cmd_loop, "fresh": cmd_fresh, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
