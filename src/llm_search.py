"""Muse-guided adversarial fault search (Meta Muse Spark via the OpenAI-compatible api.meta.ai endpoint).

  export MUSE_API_KEY=...            # never committed / logged
  python src/llm_search.py --seed 0 --budget 300 --batch 8 --workers 4   -> data/cmp/muse_seed0.jsonl

Each round the model gets: the fault-space schema + ranges, the spacecraft/policy description, the
discovered violation signatures so far, and a compacted history of tried scenarios with outcomes and
near-miss margins. It returns a batch of new scenarios as strict JSON; we validate/clamp them to exactly
the same space random search samples from (<=2 RW faults on distinct wheels, <=1 heater, <=1 leak),
run them, and repeat until the sim budget is spent. Every LLM call is logged (latency, tokens) to
data/cmp/muse_seed<S>_calls.jsonl (prompt/response text included, key never stored).
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
from search import T_end, _run, sample_params  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = os.environ.get("MUSE_BASE_URL", "https://api.meta.ai/v1")
MODEL = os.environ.get("MUSE_MODEL", "muse-spark-1.3")


def _redact(s):
    k = os.environ.get("MUSE_API_KEY") or ""
    return s.replace(k, "[REDACTED]") if k else s


def chat(messages, seed, max_tokens=16000, retries=6):
    """Returns (content, usage, latency_s, n_attempts). The sampling seed changes per retry: with a fixed seed a
    response blocked by the provider's content filter (seen intermittently) or truncated would just repeat."""
    last = None
    for a in range(retries):
        body = json.dumps({"model": MODEL, "messages": messages, "max_tokens": max_tokens,
                           "response_format": {"type": "json_object"}, "seed": seed + 7919 * a}).encode()
        req = urllib.request.Request(BASE_URL + "/chat/completions", data=body, method="POST", headers={
            "Authorization": "Bearer " + os.environ["MUSE_API_KEY"], "Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                d = json.loads(r.read())
            lat = time.perf_counter() - t0
            content = d["choices"][0]["message"].get("content")
            if not content:
                raise ValueError(f"empty content, finish_reason={d['choices'][0].get('finish_reason')}")
            json.loads(content)   # truncated / invalid JSON -> retry
            return content, d.get("usage", {}), lat, a + 1
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {_redact(e.read().decode(errors='replace')[:300])}"
        except Exception as e:  # noqa: BLE001
            last = _redact(f"{type(e).__name__}: {e}")
        print(f"  LLM call failed (attempt {a+1}): {last}", flush=True)
        time.sleep(2 * (a + 1))
    raise RuntimeError(last)


# ------------------------------------------------------------------ schema / validation
def schema_text():
    R, Te = ff_sim.RANGES, T_end()
    return f"""Scenario JSON schema (all fields required; use null for absent faults):
{{"hypothesis": str (<=20 words, the failure mechanism you are probing),
  "orbit": {{"beta_deg": float [{R['beta_deg'][0]}, {R['beta_deg'][1]}], "f0_deg": float [0, 360)}},
  "rw_faults": list of 0-2 objects on DISTINCT wheels:
      {{"wheel": int 0-3, "onset_s": float [0, {R['onset_frac'][1]*Te:.0f}], "type": "torque_derate"|"friction",
       "severity": float [{R['rw_severity'][0]}, {R['rw_severity'][1]}]}},
  "heater": null | {{"onset_s": float [0, {R['onset_frac'][1]*Te:.0f}], "power_W": float [{R['heater_W'][0]}, {R['heater_W'][1]}]}},
  "torque_leak": null | {{"onset_s": float [0, {R['onset_frac'][1]*Te:.0f}], "mag_Nm": float [{R['leak_Nm'][0]:.1e}, {R['leak_Nm'][1]:.1e}],
                         "axis": [x, y, z] body-frame direction (normalized by us)}}}}"""


def system_text():
    C, P, Te = ff_sim.CFG, ff_sim.POLICY, T_end()
    return f"""You are FaultForge, a verification engineer stress-testing spacecraft fault protection in simulation. Your job:
propose multi-fault test scenarios under which the EXISTING recovery policy fails a safety requirement, and find as many
physically DISTINCT failure mechanisms as possible (not repeats of known ones).

Simulator (Basilisk): 10 kg 6U CubeSat, 500 km circular orbit, 2 orbits = {Te:.0f} s. Inertia diag {C['inertia']} kg m^2.
Body-fixed solar panel on +X_B (zenith in nominal nadir-pointing), 30 Wh battery starting at {C['soc_init']:.0%} SoC,
loads bus {C['bus_W']} W + payload {C['payload_W']} W + wheels. Solar beta angle sets eclipse fraction (beta>~68 deg: no
eclipse; beta 0: ~37% eclipse); f0 sets initial orbital phase relative to eclipse. Constant disturbance torque
{C['nominal_disturbance_Nm']} Nm. No momentum dumping. 4 reaction wheels (4 mNm, 15 mNms, 6000 rpm) on axes
wheel0=+X, wheel1=+Y, wheel2=+Z, wheel3=(1,1,1)/sqrt3, initial rpm {C['rw_init_rpm']}.
Faults: RW torque_derate (u_max *= 1-severity; severity~1 = dead wheel), RW friction (Coulomb += severity*2 mNm,
viscous += severity*2e-6), stuck-on heater (extra W), external torque leak (adds mag along axis; secular momentum).
Faults are applied at onset_s (quantized to 5 s).

Recovery policy under test (runs every 5 s):
- SoC < {P['soc_shed']} -> SAFE (payload off, sun-point panel); SAFE -> NOMINAL when SoC > {P['soc_resume']} and att err < {P['att_safe_deg']} deg after >= {P['resume_min_s']:.0f} s in SAFE.
- NOMINAL attitude error > {P['att_safe_deg']} deg for {P['att_safe_dur_s']:.0f} s (after t={C['att_grace_s']:.0f}s) -> SAFE.
- FDIR: a wheel whose |commanded - delivered| torque residual > max({P['fdir_rel']}*|cmd|, {P['fdir_abs_Nm']:.0e} Nm) for {P['fdir_persist']}
  consecutive 5 s checks is isolated (removed from control), but ONLY while more than 3 wheels are available
  (so at most one wheel is ever isolated).
Safety constraints (violations):
- battery_floor: SoC < {C['soc_floor']}.
- attitude_loss: attitude error > {C['att_err_bound_deg']} deg continuously for > {C['att_err_max_dur_s']:.0f} s (after t={C['att_grace_s']:.0f} s).
- wheel_saturation: any AVAILABLE wheel at >= {C['sat_frac']:.0%} of max speed for > {C['sat_max_dur_s']:.0f} s.

Near-miss margins reported per run (use them as a gradient): battery_margin = min SoC - floor (<0 violates),
att_err_ratio = peak attitude error / bound, att_dur_ratio = longest out-of-bound stretch / limit (>1 violates),
wheel_speed_ratio = peak available-wheel speed / saturation threshold, sat_dur_ratio (>1 violates).

{schema_text()}

Reply with ONLY a JSON object: {{"analysis": str (<=80 words), "scenarios": [ ... exactly N scenario objects ... ]}}."""


def _clamp(x, lo, hi):
    return float(min(max(float(x), lo), hi))


def validate(s, rng):
    """Clamp an LLM scenario into the random-search space. Returns (params, n_repairs)."""
    R, Te = ff_sim.RANGES, T_end()
    on_hi = R["onset_frac"][1] * Te
    fixes = 0
    o = s.get("orbit") or {}
    p = {"orbit": {"beta_deg": round(_clamp(o.get("beta_deg", 30.0), *R["beta_deg"]), 2),
                   "f0_deg": round(float(o.get("f0_deg", 0.0)) % 360.0, 2)},
         "rw_faults": [], "heater": None, "torque_leak": None}
    used = set()
    for f in (s.get("rw_faults") or [])[:2]:
        try:
            w = int(f["wheel"])
        except Exception:  # noqa: BLE001
            fixes += 1; continue
        if w not in range(4) or w in used:
            fixes += 1; continue
        used.add(w)
        typ = f.get("type") if f.get("type") in ("torque_derate", "friction") else "torque_derate"
        p["rw_faults"].append({"wheel": w, "onset_s": round(_clamp(f.get("onset_s", 0), 0, on_hi), 1), "type": typ,
                               "severity": round(_clamp(f.get("severity", 0.5), *R["rw_severity"]), 3)})
    if len(s.get("rw_faults") or []) > 2:
        fixes += 1
    hz = s.get("heater")
    if isinstance(hz, dict):
        p["heater"] = {"onset_s": round(_clamp(hz.get("onset_s", 0), 0, on_hi), 1),
                       "power_W": round(_clamp(hz.get("power_W", 3), *R["heater_W"]), 2)}
    lk = s.get("torque_leak")
    if isinstance(lk, dict):
        ax = np.array(lk.get("axis") or [0, 0, 1], float)
        if ax.shape != (3,) or not np.all(np.isfinite(ax)) or np.linalg.norm(ax) < 1e-9:
            ax = rng.normal(size=3); fixes += 1
        ax /= np.linalg.norm(ax)
        p["torque_leak"] = {"onset_s": round(_clamp(lk.get("onset_s", 0), 0, on_hi), 1),
                            "mag_Nm": float(f"{_clamp(lk.get('mag_Nm', 1e-6), *R['leak_Nm']):.3e}"),
                            "axis": [round(float(a), 4) for a in ax]}
    return p, fixes


# ------------------------------------------------------------------ history compaction
def risk(r):
    m = r["margins"]
    return max(m["att_dur_ratio"], m["sat_dur_ratio"], m["wheel_speed_ratio"], m["att_err_ratio"] * 0.8,
               1.0 - m["battery_margin"] / 0.45)


def sig(r):
    p = r["params"]
    kinds = sorted([f"rw{f['wheel']}_{f['type']}" for f in p["rw_faults"]] + (["heater"] if p["heater"] else [])
                   + (["leak"] if p["torque_leak"] else []))
    return "+".join(sorted(r["violations"])) + " <- " + (",".join(kinds) or "none")


def brief(r):
    d = {"id": r["id"], "params": r["params"], "violations": r["violations"],
         "margins": r["margins"], "isolated_wheels": r["isolated_wheels"], "final_mode": r["final_mode"]}
    return json.dumps(d, separators=(",", ":"))


def history_text(rows, last_batch_ids, n_viol=15, n_top=25):
    if not rows:
        return "No scenarios have been run yet."
    viol = [r for r in rows if r["violated"]]
    seen = set(r["id"] for r in viol[-n_viol:])
    top = [r for r in sorted(rows, key=risk, reverse=True) if r["id"] not in seen and not r["violated"]][:n_top]
    seen |= set(r["id"] for r in top)
    last = [r for r in rows if r["id"] in last_batch_ids and r["id"] not in seen]
    sigs = {}
    for r in viol:
        sigs[sig(r)] = sigs.get(sig(r), 0) + 1
    out = [f"{len(rows)} scenarios run so far, {len(viol)} violated."]
    out.append("Violation signatures found so far (violation <- injected faults: count): "
               + (json.dumps(sigs) if sigs else "none"))
    if viol:
        out.append(f"Most recent violating runs ({len(viol[-n_viol:])}):"); out += [brief(r) for r in viol[-n_viol:]]
    out.append(f"Highest-risk non-violating runs ({len(top)}):"); out += [brief(r) for r in top]
    if last:
        out.append("Rest of the last batch:"); out += [brief(r) for r in last]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=int, default=300)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true", help="continue an interrupted run from its jsonl")
    a = ap.parse_args()
    if not os.environ.get("MUSE_API_KEY"):
        sys.exit("MUSE_API_KEY not set")
    out = a.out or os.path.join(ROOT, "data", "cmp", f"muse_seed{a.seed}.jsonl")
    calls_out = out.replace(".jsonl", "_calls.jsonl")
    rng = np.random.default_rng(10_000 + a.seed)
    sysmsg = system_text()
    rows, last_ids, t0, rnd = [], set(), time.perf_counter(), 0
    if a.resume and os.path.exists(out):
        rows = [json.loads(l) for l in open(out)]
        rnd = max(r["round"] for r in rows) + 1
        last_ids = set(r["id"] for r in rows if r["round"] == rnd - 1)
        print(f"resuming at round {rnd} with {len(rows)} sims", flush=True)
    mode = "a" if a.resume else "w"
    with open(out, mode) as fo, open(calls_out, mode) as fc, Pool(a.workers) as pool:
        while len(rows) < a.budget:
            n = min(a.batch, a.budget - len(rows))
            user = (f"Round {rnd}. Sim budget left: {a.budget - len(rows)}.\n{history_text(rows, last_ids)}\n\n"
                    f"Propose exactly {n} NEW test scenarios: refine near-misses and known failures to find their "
                    f"boundaries, and also try mechanisms not yet seen. Avoid duplicating tried params.")
            # NB: the provider's content filter intermittently rejected an earlier wording that used the word
            # "exploitation" (HTTP 400 content_policy_violation); keep the prompt in plain test-engineering terms.
            msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]
            props, usage, lat, err, fallback, repairs, att = [], {}, None, 0, 0, 0, 0
            try:
                try:
                    txt, usage, lat, att = chat(msgs, seed=a.seed * 1000 + rnd, retries=2)
                except RuntimeError as e:
                    if "content_policy" not in str(e):
                        raise
                    # provider content filter fired on this prompt: retry once with a shorter history
                    user = user.replace(history_text(rows, last_ids), history_text(rows, last_ids, n_viol=6, n_top=10))
                    msgs[1]["content"] = user
                    txt, usage, lat, att = chat(msgs, seed=a.seed * 1000 + rnd + 500, retries=2)
                    att += 2
                dd = json.loads(txt)
                props = dd.get("scenarios") or []
                analysis = dd.get("analysis", "")
            except Exception as e:  # noqa: BLE001
                err, txt, analysis = _redact(str(e))[:300], None, ""
            params, hyps = [], []
            for s in props[:n]:
                try:
                    p, fx = validate(s, rng); repairs += fx
                    params.append(p); hyps.append(str(s.get("hypothesis", ""))[:200])
                except Exception:  # noqa: BLE001
                    repairs += 1
            while len(params) < n:      # model under-delivered or call failed: fill with random (counted)
                params.append(sample_params(rng)); hyps.append("<random fallback>"); fallback += 1
            fc.write(json.dumps({"round": rnd, "latency_s": lat, "attempts": att, "usage": usage, "error": err, "n_proposed": len(props),
                                 "fallback": fallback, "repairs": repairs, "analysis": analysis,
                                 "prompt_chars": len(sysmsg) + len(user), "response": txt}) + "\n"); fc.flush()
            jobs = [(len(rows) + k, None, p) for k, p in enumerate(params)]
            res = pool.map(_run, jobs)
            for r, h in zip(res, hyps):
                r["seed"] = a.seed; r["round"] = rnd; r["hypothesis"] = h; r["source"] = "muse" if h != "<random fallback>" else "fallback"
                rows.append(r); fo.write(json.dumps(r) + "\n")
            fo.flush()
            last_ids = set(r["id"] for r in res)
            nv = sum(r["violated"] for r in rows)
            print(f"seed {a.seed} round {rnd}: {len(rows)}/{a.budget} sims, {nv} violations, llm {lat or 0:.1f}s "
                  f"tok {usage.get('total_tokens')}, fallback {fallback}, err {err}, {time.perf_counter()-t0:.0f}s",
                  flush=True)
            rnd += 1
    print("wrote", out)


if __name__ == "__main__":
    main()
