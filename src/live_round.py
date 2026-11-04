"""One LIVE Muse-guided search round (needs MUSE_API_KEY): `make live`.

    python3 src/live_round.py [--n 8] [--workers 4] [--seed S] [--blind]

1. sends the same system prompt / schema as src/llm_search.py (round 0, empty history) to Muse Spark,
2. prints the scenario JSON Muse returns, validates/clamps it to the shared fault space,
3. runs every scenario in Basilisk (2 orbits, policy v1) and flags violations with their near-miss margins,
4. prints the provenance line (model id, endpoint, response id, request id) and appends everything to
   data/live/live_<UTC timestamp>.json.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402
import llm_search as LS  # noqa: E402  (prompt + validation; its chat() is not used here)
from search import T_end  # noqa: E402
from muse_client import chat_logged, ENDPOINT, MODEL  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B, Y, R, G, C, D, X = "\033[1m", "\033[33m", "\033[31m", "\033[32m", "\033[36m", "\033[2m", "\033[0m"
if os.environ.get("NO_COLOR") or not (sys.stdout.isatty() or os.environ.get("FORCE_COLOR")):
    B = Y = R = G = C = D = X = ""


def _sim(job):
    k, params = job
    r = ff_sim.run_scenario(params, telemetry=False, policy=ff_sim.get_policy("v1"))
    r["id"] = k
    return r


def fmt_margins(m):
    return (f"battery {m['battery_margin']:+.3f} SoC  att_err {m['att_err_ratio']:.2f}x bound  "
            f"att_dur {m['att_dur_ratio']:.2f}x limit  wheel {m['wheel_speed_ratio']:.2f}x sat  "
            f"sat_dur {m['sat_dur_ratio']:.2f}x")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--blind", action="store_true")
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else int(time.time()) % 100000
    sysmsg = LS.system_text_blind() if a.blind else LS.system_text()
    user = (LS.PREFACE + f"Round 0. Sim budget left: {a.n}.\n{LS.history_text([], set())}\n\n"
            f"Propose exactly {a.n} NEW test scenarios: try distinct failure mechanisms of the recovery policy.")
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]
    print(f"{B}FaultForge live round{X}  policy v1 {'(rules hidden)' if a.blind else '(rules given)'}  "
          f"{a.n} scenarios  seed {seed}")
    print(f"{C}[muse]{X} POST {ENDPOINT}  model={MODEL}  json_mode  ({len(sysmsg) + len(user)} prompt chars) ...",
          flush=True)
    txt, prov = chat_logged(msgs, seed=seed)
    print(f"{C}[muse]{X} HTTP {prov['http_status']} in {prov['latency_s']:.1f} s  "
          f"tokens {prov['usage'].get('total_tokens')}", flush=True)
    dd = json.loads(txt)
    print(f"{C}[muse]{X} analysis: {Y}\"{dd.get('analysis', '')}\"{X}")
    props = (dd.get("scenarios") or [])[:a.n]
    rng = np.random.default_rng(seed)
    params, hyps = [], []
    for k, s in enumerate(props):
        print(f"{C}[muse]{X} scenario {k}: {D}{json.dumps(s, separators=(',', ':'))}{X}")
        try:
            p, _ = LS.validate(s, rng); params.append(p); hyps.append(str(s.get("hypothesis", ""))[:120])
        except Exception as e:  # noqa: BLE001
            print(f"        {R}invalid, skipped: {e}{X}")
    print(f"{G}[sim]{X} running {len(params)} Basilisk sims (2 orbits = {T_end():,.0f} s each, policy v1) on "
          f"{a.workers} workers ...", flush=True)
    t0 = time.perf_counter(); res = [None] * len(params)
    with Pool(a.workers) as pool:
        for r in pool.imap_unordered(_sim, list(enumerate(params))):
            res[r["id"]] = r; k = r["id"]
            tag = f"{R}{B}VIOLATION {','.join(r['violations'])}{X}" if r["violated"] else f"{G}ok{X}"
            print(f"{G}[sim]{X} #{k} {tag}  {D}{hyps[k]}{X}\n        margins: {fmt_margins(r['margins'])}"
                  f"  isolated {r['isolated_wheels'] or '-'}  final {r['final_mode']}", flush=True)
            if r["violated"]:
                for t, m in r["policy_log"][:6]:
                    print(f"        {D}t={t:6.0f}s  {m}{X}")
    nv = sum(r["violated"] for r in res)
    print(f"{G}[sim]{X} {nv}/{len(res)} scenarios violated a safety constraint ({time.perf_counter() - t0:.0f} s wall)")
    os.makedirs(os.path.join(ROOT, "data", "live"), exist_ok=True)
    out = os.path.join(ROOT, "data", "live", "live_" + prov["ts_utc"].replace(":", "").replace("+0000", "Z") + ".json")
    json.dump(dict(provenance=prov, seed=seed, blind=a.blind, prompt_system=sysmsg, prompt_user=user,
                   response_verbatim=txt, runs=[{k: v for k, v in r.items() if k != "policy_log"} | {
                       "policy_log": r["policy_log"], "hypothesis": h} for r, h in zip(res, hyps)]),
              open(out, "w"), indent=1)
    line = {k: prov[k] for k in ("ts_utc", "model", "endpoint", "response_id", "request_id", "latency_s")}
    print(f"{B}[log]{X} " + json.dumps(line))
    print(f"{D}full record: {os.path.relpath(out, ROOT)}{X}")


if __name__ == "__main__":
    main()
