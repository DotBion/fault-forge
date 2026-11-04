"""Wheel-saturation rule fix (2026-11-04): re-evaluate every stored run whose outcome could change.

Bug: ff_sim accumulated time-above-98%-speed per wheel over the WHOLE run (never reset), so wheel_saturation fired on
CUMULATIVE > 60 s; the documented rule (and attitude_loss) is CONSECUTIVE. The fix can only remove wheel_saturation
violations (a cumulative counter is >= the consecutive one) and constraint checks are passive (they do not feed back
into dynamics or the policy), so only runs that recorded wheel_saturation need re-simulation.

  python src/satfix.py count      # static counts (sat-only / sat+other) per dataset -> stdout
  python src/satfix.py resim      # re-simulate every stored run with wheel_saturation under the fixed rule (resumable)
  python src/satfix.py apply      # rewrite stored datasets in place (legacy result kept as "violations_legacy")
  python src/satfix.py gates      # re-decide every gate on the corrected suite; complete early-stopped evaluations
All outputs in data/satfix/. Legacy behaviour is reproducible with FF_SAT_RULE=cumulative.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
OUT = os.path.join(D, "satfix")
os.makedirs(OUT, exist_ok=True)
RESIM = os.path.join(OUT, "resim.jsonl")
SAT = "wheel_saturation"


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def wjl(p, rows):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, p)


def ph(p):
    return hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]


def polfile(name):
    if name == "v1":
        return "v1"
    if name in ("v2", "v3"):
        return os.path.join(D, "repair", f"policy_{name}.json")
    return os.path.join(D, "gated", f"policy_{name}.json")


def suite_params():
    from search import grid_jobs
    P = {f"grid_{i}": p for i, _, p in grid_jobs()}
    for r in jl(os.path.join(D, "repair", "regress_v2.jsonl")):
        P[r["id"]] = r["params"]
    return P


def heldout_params():
    from search import sample_params
    P = {f"hmuse_{r['id']}": r["params"] for r in jl(os.path.join(D, "gated", "heldout_muse_seed100.jsonl"))}
    rng = np.random.default_rng(424242)
    P.update({f"hrand_{i}": sample_params(rng) for i in range(200)})
    return P


def fresh_params(k=0):
    from search import sample_params
    rng = np.random.default_rng(777000 + k)
    return {f"frand{k}_{i}": sample_params(rng) for i in range(200)}


def datasets():
    """yield (dataset_name, path, kind, records) ; records: list of (rec_id, field, policy, params, violations)."""
    out = []
    files = sorted(glob.glob(os.path.join(D, "cmp", "*_seed*.jsonl"))) + [os.path.join(D, "grid.jsonl")] \
        + sorted(glob.glob(os.path.join(D, "random_seed*.jsonl"))) \
        + [os.path.join(D, "gated", "heldout_muse_seed100.jsonl")] + sorted(glob.glob(os.path.join(D, "gated", "fresh", "muse_*.jsonl")))
    for p in files:
        if p.endswith("_calls.jsonl") or not os.path.exists(p):
            continue
        pol = "v1"
        out.append((os.path.relpath(p, D), p, "full", [(r["id"], "violations", pol, r["params"], r["violations"]) for r in jl(p)]))
    for v in ("v2", "v3"):
        p = os.path.join(D, "repair", f"regress_{v}.jsonl")
        rows = jl(p)
        out.append((os.path.relpath(p, D), p, "regress",
                    [(r["id"], "v1", "v1", r["params"], r["v1"]) for r in rows] + [(r["id"], "v2", v, r["params"], r["v2"]) for r in rows]))
    SP = suite_params()
    for p in sorted(glob.glob(os.path.join(D, "gated", "eval_*.jsonl"))):
        name = os.path.basename(p)[5:-6]
        out.append((os.path.relpath(p, D), p, "eval", [(r["id"], "violations", name, SP[r["id"]], r["violations"]) for r in jl(p)]))
    HP = heldout_params()
    p = os.path.join(D, "gated", "heldout_eval_v1.jsonl")
    out.append((os.path.relpath(p, D), p, "eval", [(r["id"], "violations", "v1", HP[r["id"]], r["violations"]) for r in jl(p)]))
    FP = fresh_params(0)
    p = os.path.join(D, "gated", "fresh", "random_v1_k0.jsonl")
    out.append((os.path.relpath(p, D), p, "eval", [(r["id"], "violations", "v1", FP[r["id"]], r["violations"]) for r in jl(p)]))
    return out


def legacy_of(v, rec=None):
    return v


def cmd_count(a):
    for name, _, _, recs in datasets():
        n = len(recs); viol = sum(bool(v) for *_, v in recs)
        s = sum(SAT in v for *_, v in recs); so = sum(SAT in v and len(v) == 1 for *_, v in recs)
        print(f"{name:45s} n={n:5d} violating={viol:5d} with_sat={s:4d} sat_only={so:4d}")


def _job(j):
    key, pol, params = j
    r = ff_sim.run_scenario(params, telemetry=False, policy=ff_sim.get_policy(polfile(pol)))
    return key, r


def cmd_resim(a):
    assert (os.environ.get("FF_SAT_RULE") or ff_sim.CFG["sat_rule"]) == "consecutive"
    done = {r["key"] for r in jl(RESIM)}
    jobs = {}
    for name, _, _, recs in datasets():
        for rid, field, pol, params, v in recs:
            if SAT in (v or {}):
                k = f"{pol}|{ph(params)}"
                if k not in done:
                    jobs[k] = (k, pol, params)
    print(f"resim: {len(jobs)} unique (policy, scenario) sims to run ({len(done)} done)", flush=True)
    t0 = time.time()
    with open(RESIM, "a") as f, Pool(a.workers) as pool:
        for i, (k, r) in enumerate(pool.imap_unordered(_job, list(jobs.values()))):
            f.write(json.dumps({"key": k, "violations": r["violations"], "margins": r["margins"],
                                "isolated_wheels": r["isolated_wheels"], "final_mode": r["final_mode"],
                                "min_soc": r["min_soc"], "max_att_err_after_grace_deg": r["max_att_err_after_grace_deg"],
                                "n_policy_actions": r["n_policy_actions"]}) + "\n"); f.flush()
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(jobs)} {time.time()-t0:.0f}s", flush=True)
    print("resim done", flush=True)


def resim_map():
    return {r["key"]: r for r in jl(RESIM)}


def corrected(recs, R):
    """rec_id/field -> (legacy, new) for recs with SAT."""
    ch = {}
    for rid, field, pol, params, v in recs:
        if SAT in (v or {}):
            k = f"{pol}|{ph(params)}"
            if k not in R:
                raise SystemExit(f"missing resim for {k}; run resim first")
            new = R[k]["violations"]
            # only saturation may disappear; a run that previously early-exited at 3 violation types may now run
            # further and record an additional (genuine) type - allowed, counted in impact.md as "type_added"
            assert (set(v) - {SAT}) <= set(new), (rid, v, new)
            ch[(rid, field)] = (v, new, R[k])
    return ch


def cmd_impact_rows():
    R = resim_map()
    rows = []
    for name, p, kind, recs in datasets():
        ch = corrected(recs, R)
        n = len({rid for rid, *_ in recs}) if kind != "regress" else len(recs) // 2
        flds = sorted({f for _, f, *_ in recs})
        for fld in flds:
            rr = [x for x in recs if x[1] == fld]
            old_v = sum(bool(x[4]) for x in rr)
            new_v = sum(bool(ch[(x[0], fld)][1]) if (x[0], fld) in ch else bool(x[4]) for x in rr)
            sat = sum(SAT in x[4] for x in rr); sato = sum(SAT in x[4] and len(x[4]) == 1 for x in rr)
            lost = sum(1 for x in rr if (x[0], fld) in ch and SAT not in ch[(x[0], fld)][1])
            added = sum(1 for x in rr if (x[0], fld) in ch and set(ch[(x[0], fld)][1]) - set(x[4]))
            rows.append(dict(dataset=name + ("" if kind != "regress" else f" [{fld}]"), n=len(rr), sat=sat, sat_only=sato,
                             sat_removed=lost, violating_old=old_v, violating_new=new_v, type_added=added))
    return rows


def cmd_impact(a):
    rows = cmd_impact_rows()
    json.dump(rows, open(os.path.join(OUT, "impact_rows.json"), "w"), indent=1)
    for r in rows:
        print(r)


def cmd_apply(a):
    R = resim_map()
    for name, p, kind, recs in datasets():
        ch = corrected(recs, R)
        if not ch:
            continue
        rows = jl(p)
        nchg = 0
        for r in rows:
            for fld in (("violations",) if kind != "regress" else ("v1", "v2")):
                c = ch.get((r["id"], fld))
                if not c:
                    continue
                old, new, full = c
                if new == old:
                    continue
                nchg += 1
                r[fld] = new
                lk = "violations_legacy_cumulative" if fld == "violations" else f"{fld}_legacy_cumulative"
                r.setdefault(lk, old)
                if kind == "full":
                    r["violated"] = bool(new)
                    r["margins_legacy_cumulative"] = r.get("margins_legacy_cumulative", r.get("margins"))
                    r["margins"] = full["margins"]
            if kind == "regress":
                r["regression"] = (not r["v1"]) and bool(r["v2"]); r["fixed"] = bool(r["v1"]) and not r["v2"]
        # full-run records with sat that did not flip still get corrected margins (consecutive sat_dur_ratio)
        if kind == "full":
            for r in rows:
                c = ch.get((r["id"], "violations"))
                if c and "margins" in r:
                    if "margins_legacy_cumulative" not in r:
                        r["margins_legacy_cumulative"] = r["margins"]
                    r["margins"] = c[2]["margins"]
        wjl(p, rows)
        print(f"{name}: {nchg} records changed", flush=True)
    # regress summaries
    sys.argv = sys.argv[:1]
    for v in ("v2", "v3"):
        rows = jl(os.path.join(D, "repair", f"regress_{v}.jsonl"))
        sp = os.path.join(D, "repair", f"regress_{v}_summary.json")
        old = json.load(open(sp))

        def s(rr):
            return {"n": len(rr), "v1_violating": sum(bool(r["v1"]) for r in rr), "v2_violating": sum(bool(r["v2"]) for r in rr),
                    "regressions": sum(r["regression"] for r in rr), "fixed": sum(r["fixed"] for r in rr)}
        g = [r for r in rows if r["id"].startswith("grid_")]
        summ = {"grid_single_fault_plus_nominal": s(g), "nominal_only": s([r for r in g if r["nominal"]]),
                "regression_ids": [r["id"] for r in rows if r["regression"]]}
        if "all_stored_v1_search_runs" in old:
            summ["all_stored_v1_search_runs"] = s([r for r in rows if not r["id"].startswith("grid_")])
        summ["sat_rule"] = "consecutive (corrected 2026-11-04, see data/satfix/impact.md)"
        summ["legacy_cumulative"] = {k: v for k, v in old.items() if k != "legacy_cumulative"}
        json.dump(summ, open(sp, "w"), indent=1)


# ------------------------------------------------------------------ gates
def cmd_gates(a):
    import gated_repair as GR
    import gated_v2 as GV
    params, v1 = GR.load_suite()     # reads corrected regress_v2 / cmp
    keys = sorted(params)
    res = {}
    for gp in sorted(glob.glob(os.path.join(D, "gated", "*_gate.json"))):
        x = json.load(open(gp))
        name, basen = x["name"], x.get("base", "v1")
        g_old = x.get("gate", {})
        if not x.get("change") or not os.path.exists(GR.pol_path(name)):
            res[name] = {"decision_old": x["decision"], "decision_new": x["decision"], "note": "no valid change"}
            continue
        mode = "budget" if x.get("phase") == "budget" else "strict"
        base = v1 if basen == "v1" else {r["id"]: r["violations"] for r in jl(os.path.join(D, "gated", f"eval_{basen}.jsonl"))}
        ep = os.path.join(D, "gated", f"eval_{name}.jsonl")
        cand = {r["id"]: r["violations"] for r in jl(ep)}

        def stop(done):
            if mode == "strict":
                return sum(len(set(v) - set(base[k])) for k, v in done.items()) >= 3
            return sum(1 for k, v in done.items() if v and not base[k]) > GV.MAX_CLEAN_BREAKS
        completed_now = False
        if len(cand) < len(keys) and not stop(cand):
            # the early stop was triggered (partly) by saturation violations that the fixed rule removes: continue
            prev = g_old.get("new_violation_ids", [])
            order = list(dict.fromkeys([k for k in prev if k in params] + [k for k in keys if k.startswith("grid_")] + keys))
            print(f"  {name}: early stop no longer justified on corrected data ({len(cand)}/{len(keys)}), continuing", flush=True)
            cand, _ = GV.evaluate(name, [(k, params[k]) for k in order], ep, a.workers, stop)
            completed_now = True
        g = GR.compare(base, cand, keys); g["complete"] = len(cand) >= len(keys)
        g["clean_broken_ids"] = [k for k in g["new_violation_ids"] if not base[k]]
        g["net_fixes"] = g["fixes"] - g["runs_with_new_violations"]
        if mode == "strict":
            ok = g["complete"] and g["new_violations"] == 0 and g["fixes"] > 0
        else:
            ok = g["complete"] and g["clean_to_violating"] <= GV.MAX_CLEAN_BREAKS and g["net_fixes"] > 0
        dec = "accept" if ok else "reject"
        res[name] = {"mode": mode, "base": basen, "change": x["change"], "decision_old": x["decision"], "decision_new": dec,
                     "old": {k: g_old.get(k) for k in ("evaluated", "new_violations", "runs_with_new_violations",
                                                       "clean_to_violating", "fixes", "net_fixes", "complete")},
                     "new": {k: g.get(k) for k in ("evaluated", "new_violations", "runs_with_new_violations",
                                                   "clean_to_violating", "fixes", "net_fixes", "complete", "violating_runs",
                                                   "violating_runs_base")},
                     "evaluation_continued_after_fix": completed_now, "clean_broken_ids": g["clean_broken_ids"],
                     "new_violation_ids": g["new_violation_ids"], "fix_ids": g["fix_ids"]}
        print(f"  {name} ({mode}, base {basen}): {x['decision']} -> {dec}  old={res[name]['old']} new={res[name]['new']}", flush=True)
    json.dump(res, open(os.path.join(OUT, "gates_corrected.json"), "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["count", "resim", "impact", "apply", "gates"])
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()
    {"count": cmd_count, "resim": cmd_resim, "impact": cmd_impact, "apply": cmd_apply, "gates": cmd_gates}[a.cmd](a)
