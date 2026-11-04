"""Gated repair, phase 2 (after the strict parameter-only loop in gated_repair.py found no zero-regression patch).

  python src/gated_v2.py structural   # Muse proposes ONE structural FDIR rule change (fdir_hard_Nm | fdir_readmit_s),
                                      # up to 2 attempts, STRICT gate (0 new violations, fixes > 0) on the full suite
  python src/gated_v2.py budget       # budget-mode rounds: accept iff fixes - regressed runs > 0 AND <= 3 previously
                                      # clean runs break (0.1% of 3,508); each broken run saved as a replayable waiver
  python src/gated_v2.py fresh        # per policy in the chain: FRESH Muse search (new seed, 100 sims) + fresh random 200
  python src/gated_v2.py report       # summary_v2.json, rejects_table.md, waivers.md, plots/gated_repair_trend.png
All artefacts in data/gated/ (written once, evaluations append per run -> resumable).
"""
import argparse
import glob
import json
import os
import sys
import time
from collections import Counter
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
import repair as R  # noqa: E402
import gated_repair as GR  # noqa: E402

ROOT, G = GR.ROOT, GR.G
WAIV = os.path.join(G, "waivers"); FRESH = os.path.join(G, "fresh")
os.makedirs(WAIV, exist_ok=True); os.makedirs(FRESH, exist_ok=True)
STRUCT_KEYS = ("fdir_hard_Nm", "fdir_readmit_s")
MAX_CLEAN_BREAKS = 3
FRESH_MUSE, FRESH_RANDOM = 100, 200
jl, pol_path, get_pol = GR.jl, GR.pol_path, GR.get_pol


def evaluate(polname, items, out_path, workers, stop=None):
    """Like GR.evaluate but with an arbitrary stop(done) predicate checked after each run."""
    done = {r["id"]: r["violations"] for r in jl(out_path)}
    todo = [(k, p, polname) for k, p in items if k not in done]
    if stop and stop(done):
        return done, False
    t0 = time.time()
    with open(out_path, "a") as f, Pool(workers) as pool:
        for i, (k, v) in enumerate(pool.imap(GR._job, todo, chunksize=2)):
            done[k] = v; f.write(json.dumps({"id": k, "violations": v}) + "\n"); f.flush()
            if (i + 1) % 250 == 0:
                print(f"    {polname}: {i+1}/{len(todo)} {time.time()-t0:.0f}s", flush=True)
            if stop and stop(done):
                pool.terminate(); return done, False
    return done, len(done) >= len(items)


def all_rejects():
    out = []
    for p in sorted(glob.glob(os.path.join(G, "*_gate.json"))):
        x = json.load(open(p))
        if x.get("decision") == "reject":
            out.append(x)
    return out


def reject_summary(rejects, params):
    lines = []
    for x in rejects:
        g = x.get("gate", {})
        rc = Counter(GR.sig(params[k]) for k in g.get("new_violation_ids", []))
        fc = Counter(GR.sig(params[k]) for k in g.get("fix_ids", []))
        lines.append(f"- {x['name']} {json.dumps(x['change'])}: {g.get('new_violations', 0)} new violations "
                     f"({g.get('clean_to_violating', 0)} on previously clean runs), {g.get('fixes', 0)} fixes, "
                     f"{g.get('evaluated', 0)} runs evaluated{'' if g.get('complete') else ' (stopped early)'}; regressed: "
                     f"{', '.join(f'{k} [{s}]' for k, s in zip(g.get('new_violation_ids', [])[:6], [GR.sig(params[k]) for k in g.get('new_violation_ids', [])[:6]]))}; "
                     f"fixed signatures: {json.dumps(dict(fc.most_common(8)))}")
    return "\n".join(lines)


def run_gate(name, cur, base, change, params, keys, prev_ids, workers, mode):
    P = get_pol(cur)
    newp = {k: v for k, v in P.items() if k != "name"} | change
    json.dump({"name": name, "base": cur, "params": newp, "change_vs_base": change}, open(pol_path(name), "w"), indent=1)
    grid = [k for k in keys if k.startswith("grid_")]
    order = list(dict.fromkeys(prev_ids + grid + keys))

    def stop(done):
        if mode == "strict":
            return sum(len(set(v) - set(base[k])) for k, v in done.items()) >= 3
        return sum(1 for k, v in done.items() if v and not base[k]) > MAX_CLEAN_BREAKS
    t0 = time.time()
    d, complete = evaluate(name, [(k, params[k]) for k in order], os.path.join(G, f"eval_{name}.jsonl"), workers, stop)
    g = GR.compare(base, d, keys); g["complete"] = complete; g["eval_s"] = round(time.time() - t0); g["mode"] = mode
    g["clean_broken_ids"] = [k for k in g["new_violation_ids"] if not base[k]]
    g["net_fixes"] = g["fixes"] - g["runs_with_new_violations"]
    if mode == "strict":
        ok = complete and g["new_violations"] == 0 and g["fixes"] > 0
        why = (f"accepted (strict): 0 new violations, {g['fixes']} fixes on all {g['evaluated']} runs" if ok else
               f"rejected (strict): {g['new_violations']} new violations in {g['runs_with_new_violations']} runs "
               f"({g['clean_to_violating']} previously clean), {g['fixes']} fixes, {g['evaluated']} runs evaluated"
               + ("" if complete else " (stopped early)"))
    else:
        ok = complete and g["clean_to_violating"] <= MAX_CLEAN_BREAKS and g["net_fixes"] > 0
        why = (f"accepted (budget): {g['fixes']} fixes, {g['runs_with_new_violations']} runs with new violations "
               f"({g['clean_to_violating']} previously clean = waived), net +{g['net_fixes']} on all {g['evaluated']} runs"
               if ok else
               f"rejected (budget): {g['clean_to_violating']} previously clean runs broken (max {MAX_CLEAN_BREAKS}), "
               f"{g['runs_with_new_violations']} runs with new violations, {g['fixes']} fixes, net {g['net_fixes']}, "
               f"{g['evaluated']} runs evaluated" + ("" if complete else " (stopped early)"))
    return ("accept" if ok else "reject"), why, g


def ask_muse(name, sys_text, user, seed):
    import llm_search as L
    rp = os.path.join(G, f"{name}_response.json")
    if not os.path.exists(rp):
        open(os.path.join(G, f"{name}_prompt.txt"), "w").write(sys_text + "\n\n" + user)
        content, usage, lat, att = L.chat([{"role": "system", "content": sys_text}, {"role": "user", "content": user}],
                                          seed=seed, max_tokens=16000)
        json.dump({"model": L.MODEL, "latency_s": lat, "attempts": att, "usage": usage, "response_verbatim": content,
                   "parsed": json.loads(content)}, open(rp, "w"), indent=1)
    return json.load(open(rp))["parsed"]


def chain_state():
    """Current accepted policy and its suite violations, following accepted structural/budget gates in order."""
    params, v1 = GR.load_suite()
    chain = [("v1", None)]
    for rp in sorted(glob.glob(os.path.join(G, "round*.json"))):   # strict parameter-only loop (gated_repair.py)
        r = json.load(open(rp))
        if r.get("accepted"):
            x = json.load(open(os.path.join(G, f"{r['accepted']}_gate.json"))); x.setdefault("phase", "strict (param)")
            chain.append((x["name"], x))
    for p in sorted(glob.glob(os.path.join(G, "s*_gate.json"))) + sorted(glob.glob(os.path.join(G, "b*_gate.json")),
                                                                          key=lambda q: (int(os.path.basename(q)[1:].split("t")[0]),
                                                                                         int(os.path.basename(q).split("t")[1].split("_")[0]))):
        x = json.load(open(p))
        if x["decision"] == "accept":
            chain.append((x["name"], x))
    cur = chain[-1][0]
    base = v1 if cur == "v1" else {r["id"]: r["violations"] for r in jl(os.path.join(G, f"eval_{cur}.jsonl"))}
    return params, v1, chain, cur, base


SYS_STRUCT = ("You are a spacecraft fault-protection engineer. Simulation-based verification found multi-fault cases where the "
              "onboard FDIR/safe-mode policy itself causes a safety violation. Many PARAMETER-only patches were tried and all "
              "were rejected by a zero-regression gate (listed below). Propose ONE STRUCTURAL change to the FDIR logic, chosen "
              "from the structural options offered, with its parameter. Hard gate: tested on 3,508 regression runs and REJECTED "
              "if it introduces even one new violation. Write in plain reliability-engineering wording.")


def cmd_structural(a):
    params, v1, chain, cur, base = chain_state()
    keys = sorted(params)
    if any(n.startswith("s") for n, _ in chain[1:]):
        print("structural already accepted:", cur); return
    cases = GR.failing_cases(cur, a.workers)
    attempts = []
    for k in (1, 2):
        name = f"s{k}"
        gp = os.path.join(G, f"{name}_gate.json")
        if os.path.exists(gp):
            x = json.load(open(gp)); attempts.append(x); print(f"  {name}: (cached) {x['decision']} {x['gate_reason']}")
            if x["decision"] == "accept":
                return
            continue
        base_prompt = GR.build_prompt(1, 1, cur, cases, [], [], a.workers)   # policy text, cases, representative traces
        rej = all_rejects()
        rej_names = [x["name"] for x in rej]
        # regression traces from the most informative earlier rejects (latest structural attempt, else r1t3: full suite)
        src = attempts[-1] if attempts else next((x for x in rej if x["name"] == "r1t3"), rej[-1])
        ids = src["gate"]["new_violation_ids"][:4]
        with Pool(a.workers) as pool:
            trc = pool.map(GR._trace, [(params[i], src["name"]) for i in ids])
            trb = pool.map(GR._trace, [(params[i], cur) for i in ids])
        struct_opts = "\n".join(f'  "{s}": {R.WHITELIST[s][0]} [{R.WHITELIST[s][1]}, {R.WHITELIST[s][2]}] - {R.WHITELIST[s][3]}'
                                for s in STRUCT_KEYS)
        extra = (f"\n\nALL REJECTED PROPOSALS SO FAR ({len(rej)}; regression evaluation stops early, so lists are partial):\n"
                 + reject_summary(rej, params)
                 + f"\nRegression traces for {src['name']} (with the rejected change vs the current policy):\n"
                 + json.dumps([{"id": i, "faults": GR.faults_of(params[i]), "with_rejected": c, "with_current": b}
                               for i, c, b in zip(ids, trc, trb)], separators=(",", ":"))
                 + f"\n\nSTRUCTURAL OPTIONS (choose exactly ONE key, value within range; nothing else may change):\n{struct_opts}\n"
                 + "Reply with ONLY a JSON object: {\"diagnosis\": str (<=120 words), \"change\": {one structural key: value}, "
                   "\"rule_in_words\": str (<=60 words), \"rationale\": str (<=150 words), \"why_no_regressions\": str (<=100 words), "
                   "\"ideal_rule_if_unconstrained\": str (<=60 words)}")
        user = base_prompt.split("Reply with ONLY a JSON object:")[0] + extra
        resp = ask_muse(name, SYS_STRUCT, user, seed=7000 + k)
        ch = {kk: v for kk, v in (resp.get("change") or {}).items() if kk in STRUCT_KEYS}
        ch = dict(list(ch.items())[:1])
        P = get_pol(cur)
        change, notes = R.validate_change(ch, {kk: P.get(kk) for kk in R.WHITELIST})
        print(f"  {name}: Muse structural change {resp.get('change')} -> {change} {notes}", flush=True)
        rec = {"name": name, "phase": "structural", "base": cur, "change_proposed": resp.get("change"), "change": change,
               "validation_notes": notes, **{f: resp.get(f) for f in ("diagnosis", "rule_in_words", "rationale",
                                                                    "why_no_regressions", "ideal_rule_if_unconstrained")},
               "evidence_rejects": rej_names}
        if not change:
            rec.update(decision="reject", gate_reason="no valid structural change", gate={"new_violation_ids": [], "fixes": 0})
        else:
            prev = [i for x in attempts for i in x["gate"]["new_violation_ids"]]
            dec, why, g = run_gate(name, cur, base, change, params, keys, prev, a.workers, "strict")
            rec.update(decision=dec, gate_reason=why, gate=g)
        json.dump(rec, open(gp, "w"), indent=1)
        print(f"  {name}: {rec['decision']} - {rec['gate_reason']}", flush=True)
        attempts.append(rec)
        if rec["decision"] == "accept":
            return


SYS_BUDGET = ("You are a spacecraft fault-protection engineer. Simulation-based verification found multi-fault cases where the "
              "onboard FDIR/safe-mode policy itself causes a safety violation. Propose ONE small policy change from the "
              "whitelist. Acceptance gate on 3,508 regression runs: (fixed runs) - (runs with any new violation) must be > 0 "
              f"AND at most {MAX_CLEAN_BREAKS} previously clean runs may break (each becomes a documented waiver). "
              "Prefer narrow changes with few side effects. Write in plain reliability-engineering wording.")


def cmd_budget(a):
    n_acc = 0
    for rnd in range(1, a.rounds + 1):
        params, v1, chain, cur, base = chain_state()
        keys = sorted(params)
        print(f"=== budget round {rnd} (current policy {cur})", flush=True)
        cases = GR.failing_cases(cur, a.workers)
        attempts, acc = [], None
        for tri in range(1, a.tries + 1):
            name = f"b{rnd}t{tri}"
            gp = os.path.join(G, f"{name}_gate.json")
            if os.path.exists(gp):
                x = json.load(open(gp)); attempts.append(x); print(f"  {name}: (cached) {x['decision']} {x['gate_reason']}")
                if x["decision"] == "accept":
                    acc = x; break
                continue
            hist = [{"policy": n, "change": x["change"]} for n, x in chain[1:]]
            user = GR.build_prompt(rnd, tri, cur, cases, attempts, hist, a.workers)
            user = user.replace("is REJECTED if it introduces even one new violation relative to the current policy", "")
            if not attempts and rnd == 1:
                user = user.replace("Reply with ONLY a JSON object:", "Earlier rejected proposals (strict and structural):\n"
                                    + reject_summary(all_rejects(), params) + "\n\nReply with ONLY a JSON object:")
            resp = ask_muse(name, SYS_BUDGET, user, seed=8000 + 10 * rnd + tri)
            P = get_pol(cur)
            change, notes = R.validate_change(resp.get("change"), {k: P.get(k) for k in R.WHITELIST} | {
                k: P[k] for k in P if k != "name"})
            print(f"  {name}: Muse change {resp.get('change')} -> {change} {notes}", flush=True)
            rec = {"name": name, "phase": "budget", "round": rnd, "try": tri, "base": cur, "change_proposed": resp.get("change"),
                   "change": change, "validation_notes": notes, "diagnosis": resp.get("diagnosis"),
                   "rationale": resp.get("rationale"), "why_no_regressions": resp.get("why_no_regressions")}
            if not change:
                rec.update(decision="reject", gate_reason="no valid change", gate={"new_violation_ids": [], "fixes": 0})
            else:
                prev = [i for x in attempts for i in x["gate"]["new_violation_ids"]]
                dec, why, g = run_gate(name, cur, base, change, params, keys, prev, a.workers, "budget")
                rec.update(decision=dec, gate_reason=why, gate=g)
                if dec == "accept":
                    rec["waivers"] = []
                    for i in g["clean_broken_ids"]:
                        f = os.path.join(WAIV, f"{name}_{i}.jsonl")
                        json.dump({"id": 0, "suite_id": i, "params": params[i], "violations": {}}, open(f, "w"))
                        open(f, "a").write("\n")
                        cv = {r["id"]: r["violations"] for r in jl(os.path.join(G, f"eval_{name}.jsonl"))}[i]
                        rec["waivers"].append({"suite_id": i, "file": os.path.relpath(f, ROOT), "violations_new": cv,
                                               "signature": GR.sig(params[i]),
                                               "replay_new": f"python3 src/replay.py {os.path.relpath(f, ROOT)} 0 --policy data/gated/policy_{name}.json",
                                               "replay_base": f"python3 src/replay.py {os.path.relpath(f, ROOT)} 0 --policy "
                                                              + ("v1" if cur == "v1" else f"data/gated/policy_{cur}.json")})
            json.dump(rec, open(gp, "w"), indent=1)
            print(f"  {name}: {rec['decision']} - {rec['gate_reason']}", flush=True)
            attempts.append(rec)
            if rec["decision"] == "accept":
                acc = rec; break
        if not acc:
            print(f"=== budget round {rnd}: nothing accepted, stopping", flush=True); break
        n_acc += 1
        print(f"=== budget round {rnd}: accepted {acc['name']}", flush=True)


def fresh_one(k, pol, workers):
    import subprocess
    from search import sample_params
    seed = 300 + k
    out = os.path.join(FRESH, f"muse_{pol}_seed{seed}.jsonl")
    if len(jl(out)) < FRESH_MUSE:
        cmd = [sys.executable, os.path.join(ROOT, "src", "llm_search.py"), "--seed", str(seed), "--budget", str(FRESH_MUSE),
               "--workers", str(workers), "--out", out, "--policy", "v1" if pol == "v1" else pol_path(pol)]
        if os.path.exists(out):
            cmd.append("--resume")
        subprocess.run(cmd, check=True)
    rng = np.random.default_rng(777000 + k)
    items = [(f"frand{k}_{i}", sample_params(rng)) for i in range(FRESH_RANDOM)]
    d, _ = evaluate(pol, items, os.path.join(FRESH, f"random_{pol}_k{k}.jsonl"), workers)
    m = jl(out)
    res = {"policy": pol, "k": k, "muse_seed": seed, "muse": {"n": len(m), "violating": sum(r["violated"] for r in m)},
           "random": {"n": len(d), "violating": sum(bool(v) for v in d.values())}}
    res["muse"]["rate"] = res["muse"]["violating"] / max(1, res["muse"]["n"])
    res["random"]["rate"] = res["random"]["violating"] / max(1, res["random"]["n"])
    res["heldout_fixed"] = GR.heldout_rate(pol, workers)
    json.dump(res, open(os.path.join(FRESH, f"result_{pol}.json"), "w"), indent=1)
    print("fresh", json.dumps(res), flush=True)
    return res


def cmd_fresh(a):
    _, _, chain, _, _ = chain_state()
    pols = [n for n, _ in chain] if a.policy is None else [a.policy]
    for k, pol in enumerate([n for n, _ in chain]):
        if pol in pols:
            fresh_one(k, pol, a.workers)


def cmd_report(a):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    params, v1, chain, cur, base = chain_state()
    keys = sorted(params)
    # suite counts per accepted policy
    trend = []
    for k, (pol, x) in enumerate(chain):
        suite = v1 if pol == "v1" else {r["id"]: r["violations"] for r in jl(os.path.join(G, f"eval_{pol}.jsonl"))}
        fr = os.path.join(FRESH, f"result_{pol}.json")
        trend.append({"policy": pol, "change": None if x is None else x["change"], "phase": None if x is None else x.get("phase"),
                      "suite_violating_runs": sum(bool(suite[i]) for i in keys if i in suite), "suite_n": len(suite),
                      "waivers": [] if x is None else x.get("waivers", []), "gate_reason": None if x is None else x["gate_reason"],
                      "fresh": json.load(open(fr)) if os.path.exists(fr) else None})
    rej = all_rejects()
    # rejects table
    L = ["# Rejected proposals (strict gate unless noted)", "",
         "Gate: strict = 0 new (run, violation) pairs vs the current policy and fixes > 0 on the full 3,508-run suite; "
         "evaluation stops early once a few new violations are found (counts are then partial). Budget = net fixes > 0 and "
         f"<= {MAX_CLEAN_BREAKS} previously clean runs broken.", "",
         "| id | phase | base | change | new violations (prev. clean runs) | fixes | runs evaluated | why rejected |", "|---|---|---|---|---|---|---|---|"]
    for x in rej:
        g = x.get("gate", {})
        ph = x.get("phase", "strict (param)")
        L.append(f"| {x['name']} | {ph} | {x.get('base', 'v1')} | `{json.dumps(x['change'])}` | {g.get('new_violations', 0)} "
                 f"({g.get('clean_to_violating', 0)}) | {g.get('fixes', 0)} | {g.get('evaluated', 0)}"
                 f"{'' if g.get('complete') else ' (early stop)'} | {x['gate_reason']} |")
    L += ["", "First regressed runs per reject (replay: `python3 src/gated_v2.py replay <suite id> --policy <id>`):", ""]
    for x in rej:
        L.append(f"- {x['name']}: " + ", ".join(f"{i} [{GR.sig(params[i])}]" for i in x.get("gate", {}).get("new_violation_ids", [])[:6]))
    open(os.path.join(G, "rejects_table.md"), "w").write("\n".join(L) + "\n")
    W = ["# Waivers: previously clean runs broken by budget-mode accepted patches", "",
         f"Budget gate allows at most {MAX_CLEAN_BREAKS} previously clean runs (0.1% of the 3,508-run suite) per accepted patch.", ""]
    nw = 0
    for t in trend:
        if t["phase"] == "budget":
            W.append(f"## {t['policy']}: change `{json.dumps(t['change'])}`  ({t['gate_reason']})")
            if not t["waivers"]:
                W.append("- no previously clean runs broken")
            for w in t["waivers"]:
                nw += 1
                W += [f"- **{w['suite_id']}** [{w['signature']}] -> {w['violations_new']}  (file `{w['file']}`)",
                      f"  - with patch: `{w['replay_new']}`", f"  - before patch: `{w['replay_base']}`"]
            W.append("")
    if len(W) == 4:
        W.append("No budget-mode patch was accepted, so there are no waivers.")
    open(os.path.join(G, "waivers.md"), "w").write("\n".join(W) + "\n")
    # plot
    fig, ax = plt.subplots(figsize=(10, 5.2)); ax2 = ax.twinx()
    xs = np.arange(len(trend)); labels = []
    for t in trend:
        lab = t["policy"] if t["change"] is None else f"{t['policy']}\n" + ", ".join(f"{k}={v}" for k, v in t["change"].items())
        labels.append(lab[:60])
    ax2.bar(xs, [t["suite_violating_runs"] for t in trend], color="0.85", width=0.5, label="gate suite: violating runs (of 3,508)")
    for i, t in enumerate(trend):
        ax2.text(i, t["suite_violating_runs"], str(t["suite_violating_runs"]), ha="center", va="bottom", fontsize=8, color="0.4")
    def ser(f):
        return [f(t) if t["fresh"] else np.nan for t in trend]
    ax.plot(xs, ser(lambda t: 100 * t["fresh"]["muse"]["rate"]), "o-", color="C3", lw=2, label="FRESH Muse search (new seed/policy, 100 sims)")
    ax.plot(xs, ser(lambda t: 100 * t["fresh"]["random"]["rate"]), "s-", color="C0", lw=2, label="FRESH random (200)")
    ax.plot(xs, ser(lambda t: 100 * t["fresh"]["heldout_fixed"]["all"]["rate"]), "^--", color="C2", alpha=0.7,
            label="fixed held-out set (300, secondary)")
    for i, t in enumerate(trend):
        if t["fresh"]:
            ax.annotate(f"{100*t['fresh']['muse']['rate']:.0f}%", (i, 100 * t["fresh"]["muse"]["rate"]), textcoords="offset points",
                        xytext=(6, 4), fontsize=8, color="C3")
        if t["phase"] == "budget":
            ax.annotate(f"waiver: {len(t['waivers'])} clean run(s) broken", (i, 0), textcoords="offset points", xytext=(-40, -38),
                        fontsize=7.5, color="C1", annotation_clip=False)
        if t["phase"] == "structural":
            ax.annotate("structural rule\n(strict gate, 0 new)", (i, 0), textcoords="offset points", xytext=(-35, -42),
                        fontsize=7.5, color="C4", annotation_clip=False)
    ax.set_xticks(xs); ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel("violation rate on fresh scenarios (%)"); ax2.set_ylabel("gate-suite violating runs")
    ax.set_zorder(ax2.get_zorder() + 1); ax.patch.set_visible(False)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7.5, loc="upper right")
    ax.set_ylim(bottom=0)
    ax.set_title(f"Gated repair: accepted policies ({len(rej)} proposals rejected by the gates)", fontsize=10)
    fig.tight_layout(); fig.subplots_adjust(bottom=0.25)
    fig.savefig(os.path.join(ROOT, "plots", "gated_repair_trend.png"), dpi=130); plt.close(fig)
    fm = [t["fresh"]["muse"]["rate"] for t in trend if t["fresh"]]
    summ = {"chain": trend, "n_rejected": len(rej), "rejected": [{"name": x["name"], "change": x["change"], "why": x["gate_reason"]} for x in rej],
            "fresh_muse_rates": fm, "trend_down_fresh_muse": bool(len(fm) > 1 and fm[-1] < fm[0]),
            "n_waivers": nw}
    json.dump(summ, open(os.path.join(G, "summary_v2.json"), "w"), indent=1)
    print(json.dumps({"chain": [(t["policy"], t["change"], t["suite_violating_runs"],
                                 t["fresh"] and (t["fresh"]["muse"]["rate"], t["fresh"]["random"]["rate"],
                                                 t["fresh"]["heldout_fixed"]["all"]["rate"])) for t in trend],
                      "n_rejected": len(rej), "trend_down_fresh_muse": summ["trend_down_fresh_muse"]}, indent=1))


def cmd_replay(a):
    params, _ = GR.load_suite()
    p = params[a.id]
    for pol in ("v1", a.policy):
        r = ff_sim.run_scenario(p, telemetry=False, policy=get_pol(pol))
        print(pol, r["violations"]); [print(f"   t={t:.0f}s {m}") for t, m in r["policy_log"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["structural", "budget", "fresh", "report", "replay"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--tries", type=int, default=4)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--policy", default=None)
    a = ap.parse_args()
    {"structural": cmd_structural, "budget": cmd_budget, "fresh": cmd_fresh, "report": cmd_report, "replay": cmd_replay}[a.cmd](a)


if __name__ == "__main__":
    main()
