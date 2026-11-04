"""Policy repair loop: Muse proposes a small whitelisted change to the safe-mode policy, we verify it.

  python src/repair.py propose  --round 1                  -> data/repair/round1_{prompt.txt,response.json}, policy_v2.json
  python src/repair.py fixes    --policy v2                -> re-run every minimized counterexample on v2
  python src/repair.py regress  --policy v2 [--all]        -> single-fault grid + nominal (and, with --all, every
                                                              stored v1 search run) on v1 vs v2
  python src/repair.py analyze  --policy v2                -> minimize the v2 search violations, summary + plots

Policies are dicts of POLICY keys (ff_sim.get_policy); v1 is the untouched original, so v1 replays are unchanged.
The model may only choose from WHITELIST below (bounded values, at most MAX_CHANGES keys per round).
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
CMP = os.path.join(ROOT, "data", "cmp")
REP = os.path.join(ROOT, "data", "repair")
os.makedirs(REP, exist_ok=True)

MAX_CHANGES = 3
# key: (kind, lo, hi, description). kind: bool | int | float | choice | float_or_null
WHITELIST = {
    "isolation_swap": ("bool", None, None, "FDIR swap: when another wheel trips the detector while one is already isolated and its "
                       "residual > swap_ratio x the isolated wheel's recorded residual, re-enable the isolated (milder) wheel and "
                       "isolate the new one (keeps 3-wheel control on the healthiest wheels)"),
    "swap_ratio": ("float", 1.2, 5.0, "residual ratio required for an FDIR swap"),
    "swap_min_res_Nm": ("float_or_null", 3e-4, 5e-3, "narrows the FDIR swap: the new wheel's residual must also be >= this "
                        "absolute value, Nm (null = no extra condition)"),
    "swap_max_iso_res_Nm": ("float_or_null", 3e-4, 5e-3, "narrows the FDIR swap: only an isolated wheel whose recorded residual "
                            "is <= this value, Nm (i.e. a mildly degraded wheel) may be re-enabled (null = no extra condition)"),
    "fdir_hard_Nm": ("float_or_null", 5e-4, 3e-3, "STRUCTURAL: reserve isolation (and swaps) for hard failures - a wheel that "
                     "trips the detector is isolated only if its residual >= this value, Nm; milder ones are only flagged "
                     "and stay in control (null = off, v1 behaviour)"),
    "fdir_readmit_s": ("float_or_null", 30.0, 1800.0, "STRUCTURAL: re-admit an isolated wheel once its (uncommanded) torque "
                       "residual has stayed <= fdir_abs_Nm for this many s; frees the single isolation for a later fault "
                       "(null = off, v1 behaviour)"),
    "min_avail": ("choice", [2, 3], None, "isolation allowed only while more than this many wheels are available "
                  "(3 = at most one isolation; 2 = a second isolation, leaving 2 wheels = under-actuated)"),
    "fdir_persist": ("int", 2, 12, "consecutive 5 s detector hits before isolating (persistence / hysteresis)"),
    "fdir_rel": ("float", 0.1, 1.0, "relative residual threshold (x |commanded torque|)"),
    "fdir_abs_Nm": ("float", 1e-4, 2e-3, "absolute residual threshold, Nm"),
    "soc_shed": ("float", 0.25, 0.55, "SoC below which NOMINAL -> SAFE (sun-pointing priority when battery is low)"),
    "soc_resume": ("float", 0.50, 0.85, "SoC above which SAFE -> NOMINAL"),
    "resume_min_s": ("float", 0.0, 1800.0, "minimum dwell in SAFE before resuming"),
    "att_safe_deg": ("float", 5.0, 30.0, "attitude-watchdog threshold, deg"),
    "att_safe_dur_s": ("float", 30.0, 600.0, "attitude-watchdog persistence, s"),
    "wheel_safe_frac": ("float_or_null", 0.80, 0.97, "momentum guard: in-use wheel >= this fraction of max speed for "
                        "wheel_safe_s -> SAFE, no resume while above (null = off)"),
    "wheel_safe_s": ("float", 10.0, 120.0, "momentum-guard persistence, s"),
}


def validate_change(ch, base):
    out, notes = {}, []
    for k, v in (ch or {}).items():
        if k not in WHITELIST:
            notes.append(f"dropped non-whitelisted key {k}"); continue
        kind, lo, hi, _ = WHITELIST[k]
        try:
            if kind == "bool":
                v = bool(v)
            elif kind == "int":
                v = int(np.clip(int(round(float(v))), lo, hi))
            elif kind == "choice":
                v = int(v)
                if v not in lo:
                    notes.append(f"dropped {k}={v} (not in {lo})"); continue
            elif kind == "float_or_null":
                v = None if v is None else float(np.clip(float(v), lo, hi))
            else:
                v = float(np.clip(float(v), lo, hi))
        except (TypeError, ValueError):
            notes.append(f"dropped unparsable {k}={v!r}"); continue
        if base.get(k) != v:
            out[k] = v
    if sum(1 for k in out if k not in ("swap_ratio", "wheel_safe_s", "swap_min_res_Nm", "swap_max_iso_res_Nm")) > MAX_CHANGES:
        notes.append(f"more than {MAX_CHANGES} rule changes; kept the first {MAX_CHANGES}")
        keep, n = {}, 0
        for k, v in out.items():
            if k in ("swap_ratio", "wheel_safe_s") or n < MAX_CHANGES:
                keep[k] = v; n += k not in ("swap_ratio", "wheel_safe_s", "swap_min_res_Nm", "swap_max_iso_res_Nm")
        out = keep
    return out, notes


def out_of_scope(m):
    return sum(1 for f in m["rw_faults"] if f["type"] == "torque_derate" and f["severity"] >= 0.9) >= 2


def load_minimized():
    rows = {}
    for l in open(os.path.join(CMP, "minimized.jsonl")):
        d = json.loads(l); rows[d["key"]] = d
    return [d for d in rows.values() if d["reproduces"]]


def policy_text(P):
    import llm_search as L
    C = ff_sim.CFG
    txt = f"""Policy parameters (current): {json.dumps({k: P[k] for k in ff_sim.POLICY})}
Logic (every 5 s):
- SoC < soc_shed -> SAFE (payload off, sun-point panel). SAFE -> NOMINAL when SoC > soc_resume and att err < att_safe_deg
  after >= resume_min_s in SAFE.
- NOMINAL attitude error > att_safe_deg for att_safe_dur_s (after t={C['att_grace_s']:.0f}s) -> SAFE.
- FDIR: wheel torque residual |commanded - delivered| > max(fdir_rel*|cmd|, fdir_abs_Nm) for fdir_persist consecutive
  checks -> wheel isolated, but only while more than {P.get('min_avail', 3)} wheels are available.
{L.policy_extra_text(P)}- No momentum dumping hardware (no magnetorquers/thrusters). Control: MRP feedback, 3-axis, wheel torque allocation
  by pseudo-inverse over available wheels (wheel0=+X, wheel1=+Y, wheel2=+Z, wheel3=(1,1,1)/sqrt3; 4 mNm, 6000 rpm)."""
    return txt


def whitelist_text():
    lines = [f'  "{k}": {kind}{"" if lo is None else f" {lo}" if kind == "choice" else f" [{lo}, {hi}]"} - {d}'
             for k, (kind, lo, hi, d) in WHITELIST.items()]
    return "Allowed changes (WHITELIST; anything else is rejected):\n" + "\n".join(lines)


def trace(params, P):
    r = ff_sim.run_scenario(params, telemetry=False, policy=P)
    return {"violations": r["violations"], "margins": {k: round(v, 3) for k, v in r["margins"].items()},
            "policy_log": [f"t={t:.0f}s {m}" for t, m in r["policy_log"]][:8], "isolated_wheels": r["isolated_wheels"]}


def pick_cases(cases, n=8):
    """Diverse representatives: round-robin over coarse patterns (largest groups first), fewest faults first."""
    groups = {}
    for d in sorted(cases, key=lambda d: (d["n_faults_after"], d["key"])):
        groups.setdefault(d["pattern_coarse"], []).append(d)
    order = sorted(groups.values(), key=len, reverse=True)
    out, i = [], 0
    while len(out) < n and any(order):
        g = order[i % len(order)]
        if g:
            out.append(g.pop(0))
        i += 1
        order = [g for g in order if g] if i % len(order) == 0 else order
    return out


def cmd_propose(a):
    import llm_search as L
    base_name = "v1" if a.round == 1 else f"v{a.round}"
    P = ff_sim.get_policy(base_name)
    mins = load_minimized()
    if a.round == 1:
        cases = [d for d in mins if d["policy_induced"] and not out_of_scope(d["minimized"])]
        context = ""
    else:
        prev = json.load(open(os.path.join(REP, f"summary_{base_name}.json")))
        cases = [json.loads(l) for l in open(os.path.join(REP, base_name, "minimized.jsonl"))]
        cases = [d for d in cases if d["reproduces"] and d["policy_induced"] and not out_of_scope(d["minimized"])]
        context = ("\nResults of the previous round (policy " + base_name + "): " +
                   json.dumps({k: prev[k] for k in ("change", "fixes", "regressions", "search") if k in prev}) +
                   "\nThe cases below are new failure cases from a fresh verification search on " + base_name + ".\n")
        rp = os.path.join(REP, f"regress_{base_name}.jsonl")
        if os.path.exists(rp):   # also show in-scope regressions (v1 survived, base_name fails), with traces
            regs = [json.loads(l) for l in open(rp)]
            regs = [r for r in regs if r["regression"] and not out_of_scope(r["params"])]
            regs = sorted(regs, key=lambda r: r["id"])[:: max(1, len(regs) // 4)][:4]
            context += ("REGRESSIONS of " + base_name + " vs v1 (v1 had no violation; the original v1 policy is the base "
                        "before all changes): " + json.dumps([{"faults": {k: r["params"][k] for k in
                        ("orbit", "rw_faults", "heater", "torque_leak")}, "with_" + base_name: trace(r["params"], P),
                        "with_v1_violations": r["v1"]} for r in regs], separators=(',', ':')) + "\n")
    stats = {}
    for d in cases:
        stats[d["pattern_coarse"]] = stats.get(d["pattern_coarse"], 0) + 1
    reps = pick_cases(cases, a.n_cases)
    ex = []
    for d in reps:
        tr = trace(d["minimized"], P)
        ex.append({"faults": {k: d["minimized"][k] for k in ("orbit", "rw_faults", "heater", "torque_leak")},
                   "with_policy": tr, "without_policy_violations": d["violations_no_policy"]})
    sysmsg = ("You are a spacecraft fault-protection engineer. Simulation-based verification found multi-fault cases in which "
              "the onboard safe-mode/FDIR policy itself causes a safety violation that would not occur with the policy "
              "disabled. Propose ONE small, concrete policy change, chosen only from the whitelist, that removes as many of "
              "these failure cases as possible without degrading behaviour in single-fault and nominal cases.")
    user = (L.PREFACE if a.round > 1 else "") + f"""Spacecraft: 6U CubeSat, 2-orbit sims, 4 reaction wheels, battery 30 Wh. Safety requirements: SoC >= 0.20; attitude
error <= 30 deg (not > 1200 s continuously after 900 s); no in-use wheel >= 98% max speed for > 60 s.
Fault types: torque_derate (u_max *= 1-severity), friction (Coulomb += severity*2 mNm), stuck heater, external torque leak.

{policy_text(P)}

{whitelist_text()}
At most {MAX_CHANGES} keys (swap_ratio / wheel_safe_s count only as tuning of their rule). Out of scope: cases with two
nearly dead wheels (already excluded).
{context}
In-scope policy-induced minimized failure cases: {len(cases)}; count by pattern (violation <- fault kinds):
{json.dumps(stats)}
Representative cases (minimized; trace = policy actions, violations with times in s, near-miss margins):
{json.dumps(ex, separators=(',', ':'))}

Reply with ONLY a JSON object:
{{"diagnosis": str (<=120 words, what in the policy causes these failures), "change": {{whitelist key: value, ...}},
 "rationale": str (<=150 words, why this change fixes them), "expected_fixed_patterns": [str], "risks": str (<=80 words)}}"""
    open(os.path.join(REP, f"round{a.round}_prompt.txt"), "w").write(sysmsg + "\n\n" + user)
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]
    t0 = time.time()
    content, usage, lat, att = L.chat(msgs, seed=900 + a.round, max_tokens=16000)
    resp = json.loads(content)
    change, notes = validate_change(resp.get("change"), P)
    newname = f"v{a.round + 1}"
    pol = {"name": newname, "base": base_name, "params": {**{k: P[k] for k in P if k != "name"}, **change},
           "change_vs_base": change, "validation_notes": notes}
    pol["params"].pop("name", None)
    json.dump(pol, open(os.path.join(REP, f"policy_{newname}.json"), "w"), indent=1)
    json.dump({"round": a.round, "model": L.MODEL, "latency_s": lat, "attempts": att, "usage": usage,
               "n_cases_in_scope": len(cases), "pattern_counts": stats, "representatives": ex,
               "response_verbatim": content, "parsed": resp, "accepted_change": change, "validation_notes": notes},
              open(os.path.join(REP, f"round{a.round}_response.json"), "w"), indent=1)
    print(f"round {a.round}: {len(cases)} in-scope policy-induced cases, {len(reps)} shown; latency {lat:.0f}s, "
          f"attempts {att}, usage {usage.get('total_tokens')}")
    print("change:", change, notes)
    print("diagnosis:", resp.get("diagnosis")); print("rationale:", resp.get("rationale")); print("risks:", resp.get("risks"))


# ------------------------------------------------------------------ verification
def _run_pair(job):
    key, params, polname = job
    r = ff_sim.run_scenario(params, telemetry=False, policy=ff_sim.get_policy(polname))
    return key, {"violations": r["violations"], "isolated_wheels": r["isolated_wheels"], "final_mode": r["final_mode"],
                 "margins": r["margins"], "policy_log": [f"t={t:.0f}s {m}" for t, m in r["policy_log"]]}


def cmd_fixes(a):
    mins = load_minimized()
    jobs = [(d["key"], d["minimized"], a.policy) for d in mins]
    out = {}
    with Pool(a.workers) as pool:
        for k, r in pool.imap_unordered(_run_pair, jobs, chunksize=2):
            out[k] = r
    rows = []
    for d in mins:
        r = out[d["key"]]
        grp = ("out_of_scope" if out_of_scope(d["minimized"]) else
               "in_scope_policy_induced" if d["policy_induced"] else "not_policy_induced")
        rows.append({"key": d["key"], "group": grp, "target": d["target"], "pattern_fine": d["pattern_fine"],
                     "pattern_coarse": d["pattern_coarse"], "minimized": d["minimized"], "v1_violations": d["violations"],
                     "v2_violations": r["violations"], "target_fixed": d["target"] not in r["violations"],
                     "clean": not r["violations"], "v2_policy_log": r["policy_log"]})
    with open(os.path.join(REP, f"fixes_{a.policy}.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    summ = {}
    for g in ("in_scope_policy_induced", "out_of_scope", "not_policy_induced", "all"):
        rr = [r for r in rows if g == "all" or r["group"] == g]
        pats = {}
        for r in rr:
            pats.setdefault(r["pattern_fine"], []).append(r["clean"])
        summ[g] = {"n": len(rr), "target_fixed": sum(r["target_fixed"] for r in rr), "clean": sum(r["clean"] for r in rr),
                   "new_violation_type": sum(r["target_fixed"] and not r["clean"] for r in rr),
                   "patterns": len(pats), "patterns_all_clean": sum(all(v) for v in pats.values())}
    json.dump(summ, open(os.path.join(REP, f"fixes_{a.policy}_summary.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


def cmd_regress(a):
    from search import grid_jobs
    jobs = [(f"grid_{i}", p, pol) for i, _, p in grid_jobs() for pol in ("v1", a.policy)]
    if a.all:
        for path in sorted(glob.glob(os.path.join(CMP, "*_seed*.jsonl"))):
            if path.endswith("_calls.jsonl"):
                continue
            arm = os.path.basename(path)[:-6]
            for l in open(path):
                r = json.loads(l)
                jobs.append((f"{arm}_{r['id']}", r["params"], a.policy))
                # v1 result already stored in the search file (runs are deterministic)
    res = {}
    t0 = time.time()
    with Pool(a.workers) as pool:
        for i, (k, r) in enumerate(pool.imap_unordered(_run_pair, [(f"{k}|{pol}", p, pol) for k, p, pol in jobs], chunksize=4)):
            res[k] = r
            if (i + 1) % 200 == 0:
                print(f"  {i+1}/{len(jobs)} {time.time()-t0:.0f}s", flush=True)
    v1 = {}
    for path in sorted(glob.glob(os.path.join(CMP, "*_seed*.jsonl"))):
        if path.endswith("_calls.jsonl"):
            continue
        arm = os.path.basename(path)[:-6]
        for l in open(path):
            r = json.loads(l); v1[f"{arm}_{r['id']}"] = (r["violations"], r["params"])
    rows = []
    for k in sorted({k.split("|")[0] for k in res}):
        if k.startswith("grid_"):
            a1 = res[f"{k}|v1"]["violations"]
            params = next(p for i, _, p in grid_jobs() if f"grid_{i}" == k)
        else:
            a1, params = v1[k]
        a2 = res[f"{k}|{a.policy}"]["violations"]
        rows.append({"id": k, "params": params, "v1": a1, "v2": a2, "regression": (not a1) and bool(a2),
                     "fixed": bool(a1) and not a2, "nominal": not any(params[x] for x in ff_sim.FAULT_KEYS)})
    with open(os.path.join(REP, f"regress_{a.policy}.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    def s(rr):
        return {"n": len(rr), "v1_violating": sum(bool(r["v1"]) for r in rr), "v2_violating": sum(bool(r["v2"]) for r in rr),
                "regressions": sum(r["regression"] for r in rr), "fixed": sum(r["fixed"] for r in rr)}
    g = [r for r in rows if r["id"].startswith("grid_")]
    summ = {"grid_single_fault_plus_nominal": s(g), "nominal_only": s([r for r in g if r["nominal"]]),
            "regression_ids": [r["id"] for r in rows if r["regression"]]}
    if a.all:
        summ["all_stored_v1_search_runs"] = s([r for r in rows if not r["id"].startswith("grid_")])
    json.dump(summ, open(os.path.join(REP, f"regress_{a.policy}_summary.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


def _minimize_job(job):
    import minimize as M
    from compare import patterns
    key, params, viol, polname = job
    P = ff_sim.get_policy(polname)
    target = min(viol, key=viol.get)
    n0 = M.N_SIMS[0]
    m = M.minimize(params, target, log=lambda *a: None)
    r = ff_sim.run_scenario(m, telemetry=False, policy=P)
    r_np = ff_sim.run_scenario(m, telemetry=False, policy_enabled=False)
    co, fi = patterns(target, m)
    return {"key": key, "target": target, "minimized": m, "violations": r["violations"],
            "reproduces": target in r["violations"], "policy_induced": target not in r_np["violations"],
            "violations_no_policy": r_np["violations"], "n_faults_before": len(M.components(params)),
            "n_faults_after": len(M.components(m)), "minimization_sims": M.N_SIMS[0] - n0 + 2,
            "pattern_coarse": co, "pattern_fine": fi, "policy": polname}


def arm_metrics(rows, mins):
    """mins: key -> minimized record (minimized under the policy the rows were run against)."""
    from compare import phash
    v = [r for r in rows if r["violated"]]
    first = next((i + 1 for i, r in enumerate(rows) if r["violated"]), None)
    rep = [mins[phash(r["params"])] for r in v if mins[phash(r["params"])]["reproduces"]]
    pi = [m for m in rep if m["policy_induced"]]
    pis = [m for m in pi if not out_of_scope(m["minimized"])]
    return {"sims": len(rows), "violations": len(v), "violations_per_sim": len(v) / max(len(rows), 1),
            "sims_to_first_violation": first,
            "unique_patterns_fine": len({m["pattern_fine"] for m in rep}),
            "unique_patterns_coarse": len({m["pattern_coarse"] for m in rep}),
            "unique_patterns_policy_induced": len({m["pattern_fine"] for m in pi}),
            "unique_patterns_policy_induced_in_scope": len({m["pattern_fine"] for m in pis}),
            "violating_runs_policy_induced_in_scope": len(pis),
            "out_of_scope_share": (sum(out_of_scope(m["minimized"]) for m in rep) / len(rep)) if rep else None,
            "patterns_policy_induced_in_scope": sorted({m["pattern_fine"] for m in pis})}


def cmd_analyze(a):
    from compare import phash
    d = os.path.join(REP, a.policy)
    seed, budget = a.seed, a.budget
    cache_p = os.path.join(d, "minimized.jsonl")
    cache = {}
    if os.path.exists(cache_p):
        for l in open(cache_p):
            x = json.loads(l); cache[x["key"]] = x
    v1cache = {}
    for l in open(os.path.join(CMP, "minimized.jsonl")):
        x = json.loads(l); v1cache[x["key"]] = x
    arms = {}
    for path in sorted(glob.glob(os.path.join(d, "*_seed*.jsonl"))):
        if path.endswith("_calls.jsonl"):
            continue
        arm = os.path.basename(path)[:-6].split("_seed")[0]
        v2rows = sorted((json.loads(l) for l in open(path)), key=lambda r: r["id"])[:budget]
        v1p = os.path.join(CMP, f"{arm}_seed{seed}.jsonl")
        v1rows = sorted((json.loads(l) for l in open(v1p)), key=lambda r: r["id"])[:budget]
        n = min(len(v1rows), len(v2rows))
        arms[arm] = (v1rows[:n], v2rows[:n])
    jobs = {}
    for arm, (_, v2rows) in arms.items():
        for r in v2rows:
            if r["violated"] and phash(r["params"]) not in cache:
                jobs[phash(r["params"])] = (phash(r["params"]), r["params"], r["violations"], a.policy)
    for arm, (v1rows, _) in arms.items():
        miss = [r for r in v1rows if r["violated"] and phash(r["params"]) not in v1cache]
        assert not miss, f"{arm}: {len(miss)} v1 violations not minimized - run compare.py first"
    print(f"minimizing {len(jobs)} v2 violations ({len(cache)} cached)", flush=True)
    os.environ["FF_POLICY"] = a.policy
    with open(cache_p, "a") as f, Pool(a.workers) as pool:
        for i, x in enumerate(pool.imap_unordered(_minimize_job, list(jobs.values()))):
            cache[x["key"]] = x; f.write(json.dumps(x) + "\n"); f.flush()
    res = {arm: {"v1": arm_metrics(v1, v1cache), a.policy: arm_metrics(v2, cache)} for arm, (v1, v2) in arms.items()}
    if "random" in arms:   # paired: identical scenarios under both policies
        v1, v2 = arms["random"]
        res["random"]["paired"] = {"both": sum(x["violated"] and y["violated"] for x, y in zip(v1, v2)),
                                   "v1_only": sum(x["violated"] and not y["violated"] for x, y in zip(v1, v2)),
                                   "v2_only": sum(y["violated"] and not x["violated"] for x, y in zip(v1, v2))}
    pol = json.load(open(os.path.join(REP, f"policy_{a.policy}.json")))
    summ = {"policy": a.policy, "change": pol["change_vs_base"], "base": pol["base"], "search": res}
    for k, fn in (("fixes", f"fixes_{a.policy}_summary.json"), ("regressions", f"regress_{a.policy}_summary.json")):
        if os.path.exists(os.path.join(REP, fn)):
            x = json.load(open(os.path.join(REP, fn)))
            summ[k] = x if k == "fixes" else {kk: vv for kk, vv in x.items() if kk != "regression_ids"} | {
                "n_regression_ids": len(x["regression_ids"])}
    json.dump(summ, open(os.path.join(REP, f"summary_{a.policy}.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


def _tel(params, P):
    r = ff_sim.run_scenario(params, telemetry=True, policy=P)
    T = np.array(r["telemetry"]); c = {n: i for i, n in enumerate(r["telemetry_cols"])}
    return r, T, c


def cmd_headline(a):
    """Replay one counterexample that the new policy fixes: v1 vs new policy overlay."""
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    rows = [json.loads(l) for l in open(os.path.join(REP, f"fixes_{a.policy}.jsonl"))]
    if a.key:
        h = next(r for r in rows if r["key"] == a.key)
    else:
        cand = [r for r in rows if r["group"] == "in_scope_policy_induced" and r["clean"]]
        # prefer attitude_loss with 2 faults (the one-isolation mechanism), fewest faults
        cand.sort(key=lambda r: (r["target"] != "attitude_loss", len(r["minimized"]["rw_faults"]) != 2,
                                 bool(r["minimized"]["heater"]) + bool(r["minimized"]["torque_leak"]), r["key"]))
        h = cand[0]
    p = h["minimized"]
    out = {}
    fig, ax = plt.subplots(4, 1, figsize=(11, 11), sharex=True)
    for name, P, ls in (("v1", ff_sim.POLICY, "-"), (a.policy, ff_sim.get_policy(a.policy), "--")):
        r, T, c = _tel(p, P)
        out[name] = {"violations": r["violations"], "policy_log": [f"t={t:.0f}s {m}" for t, m in r["policy_log"]],
                     "margins": r["margins"]}
        th = T[:, c["t_s"]] / 3600
        ax[0].plot(th, T[:, c["att_err_deg"]], ls=ls, label=f"{name}: {', '.join(r['violations']) or 'no violation'}")
        ax[1].plot(th, 100 * T[:, c["soc"]], ls=ls, label=name)
        for i in range(4):
            ax[2].plot(th, T[:, c[f"rw{i}_rpm"]], ls=ls, color=f"C{i}", lw=1.1, label=f"rw{i} {name}")
        ax[3].plot(th, T[:, c["rw0_avail"]] + 2 * T[:, c["rw1_avail"]] * 0 + sum(T[:, c[f"rw{i}_avail"]] for i in range(1, 4)),
                   ls=ls, label=f"{name}: wheels in use")
        for t, m in r["policy_log"]:
            if "FDIR" in m:
                ax[3].axvline(t / 3600, ls=ls, color="k", alpha=0.4)
    ax[0].axhline(30, color="r", lw=0.8); ax[0].set_ylabel("att err [deg]"); ax[0].legend(fontsize=8)
    ax[1].axhline(20, color="r", lw=0.8); ax[1].set_ylabel("SoC [%]"); ax[1].legend(fontsize=8)
    ax[2].axhline(0.98 * 6000, color="r", lw=0.8); ax[2].axhline(-0.98 * 6000, color="r", lw=0.8)
    ax[2].set_ylabel("wheel speed [rpm]"); ax[2].legend(fontsize=7, ncol=4)
    ax[3].set_ylabel("# wheels in use"); ax[3].set_xlabel("time [h]"); ax[3].legend(fontsize=8)
    faults = "; ".join([f"rw{f['wheel']} {f['type']} {f['severity']} @{f['onset_s']:.0f}s" for f in p["rw_faults"]]
                       + ([f"heater {p['heater']['power_W']}W"] if p["heater"] else [])
                       + ([f"leak {p['torque_leak']['mag_Nm']:.1e}Nm"] if p["torque_leak"] else []))
    fig.suptitle(f"Counterexample {h['key']} (beta {p['orbit']['beta_deg']} deg): {faults}\n"
                 f"v1 (solid) vs {a.policy} (dashed); vertical lines = FDIR actions", fontsize=10)
    fig.tight_layout()
    fp = os.path.join(ROOT, "plots", f"repair_replay_{a.policy}.png"); fig.savefig(fp, dpi=120)
    json.dump({"key": h["key"], "params": p, **out}, open(os.path.join(REP, f"headline_{a.policy}.json"), "w"), indent=1)
    print("wrote", fp); print(json.dumps(out, indent=1, default=str))


def cmd_plot(a):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    pols = a.policies.split(",")
    S = {p: json.load(open(os.path.join(REP, f"summary_{p}.json"))) for p in pols}
    arms = [x for x in ("muse", "cmaes", "random") if x in S[pols[0]]["search"]]
    fig, ax = plt.subplots(1, 3, figsize=(17, 4.8))
    labels = ["v1"] + pols
    w = 0.8 / len(labels)
    for j, lab in enumerate(labels):
        vr, up = [], []
        for arm in arms:
            src = S[pols[0]]["search"][arm]["v1"] if lab == "v1" else S[lab]["search"].get(arm, {}).get(lab)
            vr.append(src["violations_per_sim"] if src else np.nan)
            up.append(src["unique_patterns_policy_induced_in_scope"] if src else np.nan)
        xx = np.arange(len(arms)) + (j - (len(labels) - 1) / 2) * w
        ax[0].bar(xx, vr, w, label=lab); ax[1].bar(xx, up, w, label=lab)
    n = S[pols[0]]["search"][arms[0]]["v1"]["sims"]
    for k, t in ((0, f"Violation rate, fresh search vs each policy ({n} sims, seed {a.seed})"),
                 (1, "Unique in-scope policy-induced patterns")):
        ax[k].set_xticks(np.arange(len(arms)), arms); ax[k].set_title(t, fontsize=10); ax[k].legend(); ax[k].grid(alpha=0.3, axis="y")
    groups = ["in_scope_policy_induced", "not_policy_induced", "out_of_scope"]
    for j, p in enumerate(pols):
        f = S[p]["fixes"]
        cl = [f[g]["clean"] / max(f[g]["n"], 1) for g in groups]
        tf = [f[g]["target_fixed"] / max(f[g]["n"], 1) for g in groups]
        xx = np.arange(len(groups)) + (j - (len(pols) - 1) / 2) * 0.35
        ax[2].bar(xx, tf, 0.35, alpha=0.35, color=f"C{j+1}")
        ax[2].bar(xx, cl, 0.35, color=f"C{j+1}", label=f"{p}: clean (light = target violation gone)")
        for x_, g in zip(xx, groups):
            ax[2].text(x_, 0.02, f"n={f[g]['n']}", ha="center", fontsize=7, rotation=90)
    ax[2].set_xticks(np.arange(len(groups)), ["in-scope\npolicy-induced", "not\npolicy-induced", "out of scope\n(2 dead wheels)"])
    ax[2].set_ylim(0, 1); ax[2].set_title("Replay of all v1 minimized counterexamples: fraction fixed", fontsize=10)
    ax[2].legend(fontsize=8)
    fig.tight_layout()
    fp = os.path.join(ROOT, "plots", "repair_before_after.png"); fig.savefig(fp, dpi=130); print("wrote", fp)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("propose"); p.add_argument("--round", type=int, default=1); p.add_argument("--n-cases", type=int, default=8)
    p = sp.add_parser("fixes"); p.add_argument("--policy", default="v2"); p.add_argument("--workers", type=int, default=8)
    p = sp.add_parser("regress"); p.add_argument("--policy", default="v2"); p.add_argument("--workers", type=int, default=8)
    p.add_argument("--all", action="store_true")
    p = sp.add_parser("analyze"); p.add_argument("--policy", default="v2"); p.add_argument("--workers", type=int, default=8)
    p.add_argument("--seed", type=int, default=1); p.add_argument("--budget", type=int, default=200)
    p = sp.add_parser("headline"); p.add_argument("--policy", default="v2"); p.add_argument("--key", default=None)
    p = sp.add_parser("plot"); p.add_argument("--policies", default="v2"); p.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    {"propose": cmd_propose, "fixes": cmd_fixes, "regress": cmd_regress, "analyze": cmd_analyze,
     "headline": cmd_headline, "plot": cmd_plot}[a.cmd](a)


if __name__ == "__main__":
    main()
