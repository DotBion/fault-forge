"""Keyless replay (`make replay`, no MUSE_API_KEY needed, nothing is sent to any API).

1. Re-simulates the headline counterexample a6e8087b7a52c977 (found by Muse, seed 1, minimized) with the FDIR policy
   ON and OFF and prints violations, margins and the policy event log.
2. Replays the RECORDED Muse calls from disk with their provenance: the search call that proposed it, the
   rules-blind inference quote, and the gated-repair diagnosis / patch proposals with the gate's decisions.
   Provenance = model id, file + line, the git commit that first recorded the file (timestamp), and request ids
   where logged (calls recorded before src/muse_client.py existed did not log them; that is printed as such).
"""
import glob
import json
import os
import subprocess
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_sim  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "a6e8087b7a52c977"
B, Y, R, G, C, D, X = "\033[1m", "\033[33m", "\033[31m", "\033[32m", "\033[36m", "\033[2m", "\033[0m"
if os.environ.get("NO_COLOR") or not (sys.stdout.isatty() or os.environ.get("FORCE_COLOR")):
    B = Y = R = G = C = D = X = ""


def recorded(path):
    """(commit, ISO time) of the first commit that added `path`, or file mtime if not in git."""
    rel = os.path.relpath(path, ROOT)
    try:
        out = subprocess.run(["git", "-C", ROOT, "log", "--diff-filter=A", "--format=%h %cI", "--", rel],
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
        if out:
            h, t = out[-1].split(" ", 1)
            return f"first committed {t} (commit {h})"
    except Exception:  # noqa: BLE001
        pass
    return "not in git history (local file)"


def wrap(s, w=100, ind="      "):
    return textwrap.fill(str(s), w, initial_indent=ind, subsequent_indent=ind)


def headline():
    print(f"{B}== 1. Headline counterexample {KEY} (re-simulated now in Basilisk, a few seconds) =={X}")
    mn = next(json.loads(l) for l in open(os.path.join(ROOT, "data/cmp/minimized.jsonl"))
              if json.loads(l)["key"] == KEY)
    p = mn["minimized"]
    print(f"  pattern: {mn['pattern_fine']}   minimized in {mn['minimization_sims']} sims")
    print(f"  faults : " + "; ".join(f"rw{f['wheel']} {f['type']} sev {f['severity']} @ {f['onset_s']:.0f}s"
                                     for f in p["rw_faults"]) + f";  beta {p['orbit']['beta_deg']} deg")
    res = {}
    for tag, on in (("policy ON ", True), ("policy OFF", False)):
        r = ff_sim.run_scenario(p, policy=ff_sim.get_policy("v1"), policy_enabled=on, telemetry=False)
        res[tag] = r
        m = r["margins"]
        v = f"{R}VIOLATION {r['violations']}{X}" if r["violated"] else f"{G}no violation{X}"
        print(f"  {B}{tag}{X}: {v}   peak attitude error after grace {r['max_att_err_after_grace_deg']:.1f} deg")
        print(f"      margins: att_err {m['att_err_ratio']:.2f}x bound (30 deg), att_dur {m['att_dur_ratio']:.2f}x "
              f"limit (1200 s), wheel {m['wheel_speed_ratio']:.2f}x sat, battery {m['battery_margin']:+.3f} SoC")
        for t, msg in r["policy_log"]:
            print(f"      {D}t={t:6.0f}s  {msg}{X}")
    on, off = res["policy ON "], res["policy OFF"]
    ok = on["violated"] and not off["violated"]
    print(f"  => {'REPRODUCED' if ok else 'NOT reproduced'}: the FDIR policy itself causes the loss of attitude "
          f"(policy-induced = {mn['policy_induced']} in data/cmp/minimized.jsonl)")
    return ok


def search_call():
    print(f"\n{B}== 2. Recorded Muse SEARCH call that proposed it (role: scenario search) =={X}")
    runs = os.path.join(ROOT, "data/cmp/muse_seed1.jsonl")
    calls = os.path.join(ROOT, "data/cmp/muse_seed1_calls.jsonl")
    run = next(json.loads(l) for l in open(runs) if json.loads(l)["id"] == 173)
    c = json.loads(open(calls).read().splitlines()[run["round"]])
    print(f"  model muse-spark-1.3 (run config; per-call model id/request id not logged in search logs)")
    print(f"  source data/cmp/muse_seed1_calls.jsonl line {run['round'] + 1} (round {c['round']}), "
          f"latency {c['latency_s']:.1f} s, tokens {c['usage'].get('total_tokens')}; {recorded(calls)}")
    print(f"  Muse analysis:"); print(Y + wrap(c["analysis"]) + X)
    s = next(s for s in json.loads(c["response"])["scenarios"] if s.get("hypothesis") == run["hypothesis"])
    print(f"  proposed scenario (verbatim JSON):"); print(D + wrap(json.dumps(s)) + X)
    print(f"  -> sim run 173: violations {run['violations']}")


def blind_quote():
    print(f"\n{B}== 3. Recorded rules-BLIND call (role: blind rule inference; policy text NOT in prompt) =={X}")
    calls = os.path.join(ROOT, "data/cmp/museblind_seed1_calls.jsonl")
    c = json.loads(open(calls).read().splitlines()[4])
    print(f"  model muse-spark-1.3; data/cmp/museblind_seed1_calls.jsonl line 5 (round {c['round']}), "
          f"latency {c['latency_s']:.1f} s; {recorded(calls)}")
    print(Y + wrap('"' + c["analysis"] + '"') + X)
    print(f"  {D}(ground truth, never shown to it: fdir isolates at most one wheel, min_avail = 3){X}")


def gated():
    print(f"\n{B}== 4. Recorded gated-repair calls (roles: diagnosis, patch proposal) + gate decisions =={X}")
    gates = sorted(glob.glob(os.path.join(ROOT, "data/gated/*_gate.json")))
    if not gates:
        print("  (no gated-repair artefacts in this checkout)"); return
    for i, gp in enumerate(gates):
        g = json.load(open(gp)); name = g.get("name") or os.path.basename(gp)[:-10]
        rp = gp.replace("_gate.json", "_response.json")
        resp = json.load(open(rp)) if os.path.exists(rp) else {}
        col = G if g.get("decision") == "accept" else R
        print(f"  {B}{name}{X} model {resp.get('model', '?')} latency {resp.get('latency_s', 0):.0f}s "
              f"request id: {resp.get('request_id') or 'not logged'}; {recorded(rp if resp else gp)}")
        if i == 0 or name.startswith(("s", "b")) and name[1:2] == "1":
            print(f"    diagnosis:\n{Y}" + wrap(g.get("diagnosis", "")) + X)
        print(f"    patch proposed: {json.dumps(g.get('change_proposed'))}")
        print(f"    gate: {col}{g.get('decision')}{X} - {g.get('gate_reason')}")
    print(f"  {D}gate = checks the model does not control: every candidate is re-simulated on the full suite "
          f"(576-case grid + 2,932 stored search runs); rejections are fed back to Muse for the next try{X}")


if __name__ == "__main__":
    ok = headline()
    search_call(); blind_quote(); gated()
    print(f"\n{B}replay done{X} (no API key used).")
    sys.exit(0 if ok else 1)
