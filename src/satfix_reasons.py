"""Rewrite the human-readable gate_reason (and budget waivers) of data/gated/*_gate.json from the CORRECTED gate counts.

src/satfix.py gates re-decided every gate on the consecutive-rule suite and replaced the `gate` dict, but left the
`gate_reason` string (and, for the accepted budget patch, the `waivers` list) as written under the legacy cumulative
rule. This script makes them agree with `gate`; the old string is kept under gate_legacy_cumulative.gate_reason.
Decisions are not touched (none changed). Waiver files go to data/gated/waivers/ exactly as gated_v2.py budget writes
them.   python3 src/satfix_reasons.py
"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gated_repair as GR  # noqa: E402

ROOT, G = GR.ROOT, GR.G
params, _ = GR.load_suite()
for p in sorted(glob.glob(os.path.join(G, "*_gate.json"))):
    x = json.load(open(p)); g = x["gate"]; n = x["name"]
    nv, rn, cl, fx, ev = (g.get(k, 0) for k in ("new_violations", "runs_with_new_violations", "clean_to_violating",
                                                "fixes", "evaluated"))
    tail = (f"vs {fx} fixes on the full suite" if g.get("complete") else
            f"- {fx} fixes, evaluation stopped early after {ev} runs")
    if x.get("phase") == "budget":
        net = g.get("net_fixes", fx - rn)
        why = (f"accepted (budget): {fx} fixes, {rn} runs with new violations ({cl} previously clean = waived), "
               f"net {net:+d} on all {ev} runs" if x["decision"] == "accept" else
               f"rejected (budget): {cl} previously clean runs broken (max 3), {rn} runs with new violations, {fx} fixes, "
               f"net {net:+d}, {ev} runs evaluated" + ("" if g.get("complete") else " (stopped early)"))
    else:
        why = f"rejected (strict): {nv} new violations in {rn} runs ({cl} previously clean) {tail}".replace(") - ", "), ")
    assert (x["decision"] == "accept") == why.startswith("accepted"), (n, why)
    if why != x["gate_reason"]:
        x.setdefault("gate_legacy_cumulative", {}).setdefault("gate_reason", x["gate_reason"])
        print(f"{n}: {x['gate_reason']}\n  -> {why}")
        x["gate_reason"] = why
    if x["decision"] == "accept" and x.get("phase") == "budget":
        cur = x.get("base", "v1"); ws = []
        ev_new = {r["id"]: r["violations"] for r in GR.jl(os.path.join(G, f"eval_{n}.jsonl"))}
        for i in g.get("clean_broken_ids", []):
            f = os.path.join(G, "waivers", f"{n}_{i}.jsonl"); os.makedirs(os.path.dirname(f), exist_ok=True)
            open(f, "w").write(json.dumps({"id": 0, "suite_id": i, "params": params[i], "violations": {}}) + "\n")
            rel = os.path.relpath(f, ROOT)
            ws.append({"suite_id": i, "file": rel, "violations_new": ev_new[i], "signature": GR.sig(params[i]),
                       "replay_new": f"python3 src/replay.py {rel} 0 --policy data/gated/policy_{n}.json",
                       "replay_base": f"python3 src/replay.py {rel} 0 --policy "
                                      + ("v1" if cur == "v1" else f"data/gated/policy_{cur}.json")})
        if x.get("waivers") != ws:
            x.setdefault("gate_legacy_cumulative", {}).setdefault("waivers", x.get("waivers", []))
            x["waivers"] = ws; print(f"{n}: waivers -> {[w['suite_id'] for w in ws]}")
    json.dump(x, open(p, "w"), indent=1)
