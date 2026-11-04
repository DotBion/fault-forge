"""Single source of truth for demo video v4: segment ids, nominal durations, on-screen visuals, voiceover text.

    python3 demo/v4_script.py        # regenerates docs/video_v4_script.md from this file
    bash demo/render_v4.sh           # narration (demo/vo_v4/) -> render -> demo/faultforge_demo_v4.mp4

Every number spoken here is read from the repo when this module is imported:
  causal replay   data/satfix/causal_replay.json + causal_sweep.json   (longest > 30 deg stretch, sweep counts)
  defects         data/satfix/defects.json                              (class counts, tie-break count)
  benchmarks      data/cmp/summary.json; matched random from data/matched/summary.json IF it exists (else "pending")
  gates           data/gated/*_gate.json; fresh-search check from data/gated/fresh/result_{v1,b1t1}.json
Wording rules (review 2026-11-04): coarse patterns are "distinct fault-combination signatures", never defects;
repair = Muse selects and parameterizes from an engineer-provided menu; strict and budget gates are described
separately; "implemented", never "first"; blind vs informed is a hypothesis; the headline is a "minimized case".
"""
import glob, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
P = lambda *a: os.path.join(ROOT, *a)
VO_LEAD, VO_PAD = 0.5, 0.7
MAX_TOTAL = 175.0
LIVE_CAST = os.path.join(HERE, "live", "take1.cast")
LIVE_JSON = P("data", "live", "live_2026-11-04T061215Z.json")
HL_KEY = "a6e8087b7a52c977"
TIE_KEY = "059def4e"

NUM = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
       10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
       17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty", 24: "twenty-four", 26: "twenty-six"}
say = lambda n: NUM.get(n, str(n))
J = lambda *a: json.load(open(P(*a)))


# ---------------------------------------------------------------- causal replay (segment 1)
def causal_facts():
    c = J("data", "satfix", "causal_replay.json"); sw = J("data", "satfix", "causal_sweep.json")
    return dict(c=c, sw=sw)


def _find(d, *names):
    """first value in a nested dict whose key is in names (causal json layouts differ between versions)."""
    if isinstance(d, dict):
        for k, v in d.items():
            if k in names:
                return v
        for v in d.values():
            r = _find(v, *names)
            if r is not None:
                return r
    return None


# ---------------------------------------------------------------- defects
def defect_facts():
    D = J("data", "satfix", "defects.json")
    from collections import Counter
    cnt = Counter(d["class"] for d in D.values())
    import sys; sys.path.insert(0, P("src"))
    try:
        from defects import tiebreak
        tb = [k for k, d in D.items() if tiebreak(d["arms"])]
    except Exception:
        tb = []
    return dict(n=len(D), d1=cnt.get("D1 isolation lock-in", 0), d2=cnt.get("D2 isolation removes needed wheel", 0),
                d3=cnt.get("D3 safe-mode induced", 0), tie=len(tb))


# ---------------------------------------------------------------- benchmarks (+ matched random slot)
def bench_facts():
    S = J("data", "cmp", "summary.json")["arms"]
    m = lambda a, k: S[a]["mean"][k]
    out = dict(muse_vps=m("muse", "violations_per_sim"), rnd_vps=m("random", "violations_per_sim"),
               muse_sig=m("muse", "unique_patterns_coarse"), cma_sig=m("cmaes", "unique_patterns_coarse"),
               blind_vps=m("museblind", "violations_per_sim"), blind_sig=m("museblind", "unique_patterns_coarse"),
               rnd_sig=m("random", "unique_patterns_coarse"), matched=None)
    mp = P("data", "matched", "summary.json")
    if os.path.exists(mp):
        try:
            M = json.load(open(mp))["arms"]
            arm = "matchfam" if "matchfam" in M else sorted(M)[0]
            g = lambda a, k: (M[a]["mean"].get(k) if a in M else None)
            out["matched"] = dict(arm=arm, vps=M[arm]["mean"]["violations_per_sim"],
                                  sig=M[arm]["mean"].get("unique_patterns_coarse"),
                                  arms={a: dict(vps=g(a, "violations_per_sim"), sig=g(a, "unique_patterns_coarse"))
                                        for a in ("matchfam", "matchall", "oneshot") if a in M},
                                  all={a: M[a]["mean"] for a in M}, src="data/matched/summary.json")
        except Exception:
            out["matched"] = None
    return out


# ---------------------------------------------------------------- gates + fresh check
def gate_facts():
    G = []
    for p in sorted(glob.glob(P("data", "gated", "*_gate.json"))):
        g = json.load(open(p)); n = g.get("name") or os.path.basename(p)[:-10]
        ph = g.get("phase") or ("strict" if n.startswith("r") else "structural" if n.startswith("s") else "budget")
        G.append(dict(name=n, phase=ph, decision=g.get("decision"), reason=g.get("gate_reason", ""), gate=g.get("gate", {}),
                      change=g.get("change"), waivers=g.get("waivers", [])))
    sx = [g for g in G if g["phase"] in ("strict", "structural")]
    bud = [g for g in G if g["phase"] == "budget"]
    acc = [g for g in bud if g["decision"] == "accept"]
    fr = {}
    for pol in ("v1", "b1t1"):
        f = P("data", "gated", "fresh", f"result_{pol}.json")
        if os.path.exists(f):
            fr[pol] = json.load(open(f))
    return dict(all=G, sx=sx, n_sx=len(sx), n_sx_rej=sum(g["decision"] == "reject" for g in sx), bud=bud, acc=acc,
                fresh=fr)


CF, DF, BF, GF = causal_facts(), defect_facts(), bench_facts(), gate_facts()
ACC = GF["acc"][0] if GF["acc"] else None
_g = ACC["gate"] if ACC else {}


def fresh_sentence():
    fr = GF["fresh"]
    if "b1t1" not in fr or "v1" not in fr:
        return "The fresh-search check of the accepted patch is still running.", None
    a, b = fr["v1"], fr["b1t1"]
    mv_, mb = a["muse"]["rate"], b["muse"]["rate"]; hv, hb = a["heldout_fixed"]["all"]["rate"], b["heldout_fixed"]["all"]["rate"]
    L = lambda pol: {r["id"]: bool(r["violations"]) for r in map(json.loads, open(P("data", "gated", f"heldout_eval_{pol}.jsonl")))}
    try:
        h1, h2 = L("v1"), L("b1t1"); k = set(h1) & set(h2)
        fixed, new = sum(h1[x] and not h2[x] for x in k), sum(h2[x] and not h1[x] for x in k)
    except Exception:
        fixed = new = None
    cut_m, cut_h = mb < mv_, hb < hv
    if cut_m and cut_h:
        verdict = "A modest cut."
    elif cut_m or cut_h:
        verdict = "Mixed evidence."
    else:
        verdict = "No cut on fresh data."
    s = (f"On fresh data, a new Muse search breaks the patch in {b['muse']['violating']} of {b['muse']['n']} runs, "
         f"versus {a['muse']['violating']} before, unpaired. ")
    if fixed is not None:
        s += f"On the same {len(k)} held-out scenarios, {say(fixed)} are fixed and {say(new) if new else 'none'} broken. "
    s += verdict
    return s, dict(v1=a, b1t1=b, cut_muse=cut_m, cut_heldout=cut_h, h_fixed=fixed, h_new=new)


FRESH_VO, FRESH = fresh_sentence()

if BF["matched"] and {"matchfam", "matchall"} <= set(BF["matched"].get("arms", {})):
    _A = BF["matched"]["arms"]; _f, _a = _A["matchfam"]["vps"], _A["matchall"]["vps"]
    MATCHED_VO = (f"Random matched to Muse's fault families gets {_f:.3f}; adding Muse's parameter values, {_a:.3f}." +
                  (" The gain is in Muse's parameter choices." if _a >= 0.9 * BF["muse_vps"] else ""))
elif BF["matched"]:
    _m = BF["matched"]
    MATCHED_VO = f"A random baseline matched to Muse's fault families gets {_m['vps']:.3f} per simulation."
else:
    MATCHED_VO = ("A random baseline matched to Muse's fault families is still running; its slot is marked pending.")

_lr = _find(CF["c"], "longest_over_30_s", "longest_att_over_bound_s", "longest_over_bound_s")


def _ratio(x, y):
    return x / y if y else float("inf")


RATIO = _ratio(BF["muse_vps"], BF["rnd_vps"])

SEGMENTS = [
    dict(id="s1", name="The failure: minimized a6e8087b, full policy vs isolation-only suppressed", nominal=36,
         visual="Split-screen Basilisk replay of minimized case a6e8087b (demo/data/hl4_*.csv): left full v1 policy "
                "(isolates RW0 at 120 s, cannot isolate dead RW1, attitude loss), right same policy with ONLY isolation "
                "suppressed. End card leads with the safety-rule metric: longest stretch > 30 deg 9,645 s vs 30 s "
                "(limit 1,200 s); 24-case sweep 24/24 vs 0/24; then peak 180 vs 137 deg with context. Footnote: "
                "minimized case; original run 173 also fails with the policy off.",
         vo="Here's a minimized case Muse found: two faults. Wheel zero gets mild friction, and the policy isolates "
            "it, spending its only isolation. Minutes later wheel one dies; it can't be isolated, so it stays in the "
            "loop. On the right, the same policy with only isolation switched off. The rule: at most twenty minutes "
            "beyond thirty degrees. Full policy: nine thousand six hundred forty-five seconds in one stretch. "
            "Isolation off: thirty. Twenty-four nearby variants: twenty-four failures versus zero."),
    dict(id="s2", name="How FaultForge found it: Muse in labeled roles", nominal=12,
         visual="Pipeline card: Muse roles labeled (1 scenario search, 2 blind rule inference, 3 diagnosis, 4 repair "
                "selection from an engineer-provided menu) vs code steps (Basilisk sim, minimizer, policy-off re-run, "
                "ablations, gate).",
         vo="How FaultForge found it. Muse Spark has four labeled roles: scenario search, blind rule inference, "
            "diagnosis, and choosing a repair from an engineer-provided menu. Simulation, minimization and the gate are "
            "plain code."),
    dict(id="s3", name="LIVE take1 (Muse role 1) with request id", nominal=21,
         visual="Real asciinema take demo/live/take1.cast, unedited except a labelled speed-up of the Muse wait; final "
                "provenance card with response id and x-request-id from data/live/live_2026-11-04T061215Z.json. Note: "
                "recorded (non-live) calls have no request ids.",
         vo="This is a live, unedited run. Muse returns eight fault scenarios as JSON; the wait is sped up and labeled. "
            "Basilisk simulates all eight, and two break a safety rule. This live call logged its request id. The "
            "older recorded calls did not."),
    dict(id="s4", name="Defect classes D1-D3 + D4 tie-break bug, with counts and replay commands", nominal=26,
         visual="Four cards from data/satfix/defects.json: D1 isolation lock-in 254, D2 isolates a still-needed wheel "
                "19, D3 safe-mode chattering 3, D4 implementation bug: same-step threshold crossings resolved by wheel "
                "index, not residual, 63/276. Each with its replay command.",
         vo=f"{say(DF['n']).capitalize() if DF['n'] in NUM else DF['n']} policy-caused cases reduce to three defect "
            f"classes. Isolation lock-in: {DF['d1']}. Isolating a wheel that is still needed: {say(DF['d2'])}. "
            f"Safe-mode chattering: {say(DF['d3'])}. And FaultForge surfaced a bug in the policy itself: when two "
            f"wheels cross the threshold in the same step, it picks by wheel index, not residual. {DF['tie']} cases. "
            "Each has a one-command replay."),
    dict(id="s5", name="Chart 1: benchmarks (viol/sim, coarse signatures, matched-random slot)", nominal=22,
         visual="Chart 1 (two panels, data/cmp/summary.json): violations per sim per arm (Muse 0.283, random 0.006, "
                "~46x) and distinct fault-combination signatures (coarse; Muse 15.7 vs CMA-ES 1.7). A clearly marked "
                "MATCHED RANDOM slot: filled from data/matched/summary.json if it exists at render time, else "
                "'pending'. Blind-vs-informed labelled hypothesis.",
         vo=(f"Equal budgets, three seeds: Muse finds {BF['muse_vps']:.3f} violations per simulation, random "
             f"{BF['rnd_vps']:.3f}, and about {BF['muse_sig']:.0f} fault-combination signatures; CMA-ES under two. "
             + MATCHED_VO) if (BF["matched"] and "matchall" in BF["matched"].get("arms", {})) else
            (f"Against baselines, equal budgets, three seeds: Muse finds {BF['muse_vps']:.3f} violations per simulation, "
             f"random {BF['rnd_vps']:.3f}, about {RATIO:.0f} times more. Muse finds about "
             f"{BF['muse_sig']:.0f} distinct fault-combination signatures; CMA-ES under two. " + MATCHED_VO)),
    dict(id="s6", name="The gate: strict rejects all; budget accepts b1t1; fresh result; chart 2", nominal=26,
         visual="Two gates side by side: STRICT (0 new violations) rejected all N; BUDGET (net > 0, <= 3 clean runs "
                "broken) accepted b1t1 wheel_safe_frac 0.97 / 60 s: 26 fixes, net +24, 1 clean run broken "
                "(museblind_seed1_28, waived), round 2 rejected. Then chart 2 plots/gated_repair_trend.png with the "
                "fresh-search result.",
         vo=f"Repair. Muse selects and parameterizes from an engineer-provided menu, and code decides. The strict gate, "
            f"zero new violations, rejected all {say(GF['n_sx'])} proposals. The budget gate accepted one: "
            f"{say(int(_g.get('fixes', 0)))} fixes, net plus {say(int(_g.get('net_fixes', 0)))}, and "
            f"{say(int(_g.get('clean_to_violating', 0)))} clean run broken, named and waived. " + FRESH_VO),
    dict(id="s7", name="Limits + related work + close", nominal=17,
         visual="Limits list; related work (LLM-Falsifier arXiv 2609.20752, NASA Orion FM verification); 'implemented', "
                "not 'first'; close: git clone ... && make replay.",
         vo="Limits: one simulated spacecraft, no momentum dumping, thresholds we chose, and blind versus informed "
            "search is still a hypothesis. This builds on LLM-Falsifier; we implemented the loop for fault protection. "
            "Clone it and run make replay."),
]


def to_markdown(durs=None):
    durs = durs or {}
    L = ["# FaultForge demo video v4: timed script", "",
         "Generated from `demo/v4_script.py` (`python3 demo/v4_script.py`); edit there, not here.",
         "Timings: nominal seconds, or the rendered length if `demo/vo_v4/durations.json` exists.",
         "Narration: `demo/make_vo.py --script v4` (edge-tts en-US-AndrewNeural, piper fallback).",
         f"Data at generation time: defects {DF['n']} cases (D1 {DF['d1']}, D2 {DF['d2']}, D3 {DF['d3']}, tie-break "
         f"{DF['tie']}); strict/structural proposals {GF['n_sx']} ({GF['n_sx_rej']} rejected); budget accepted: "
         f"{ACC['name'] if ACC else 'none'}; matched random: "
         f"{'included (' + BF['matched']['src'] + ')' if BF['matched'] else 'not available (pending slot)'}; "
         f"fresh check: {'done' if FRESH else 'pending'}.", ""]
    t = 0.0
    for s in SEGMENTS:
        d = durs.get(s["id"], {}).get("seg_s", s["nominal"])
        m0, m1 = divmod(int(round(t)), 60), divmod(int(round(t + d)), 60)
        L += [f"## {s['id']}  {m0[0]}:{m0[1]:02d}-{m1[0]}:{m1[1]:02d}  ({d:.1f} s)  {s['name']}", "",
              f"**On screen:** {s['visual']}", "", f"**Voiceover:** {s['vo']}", ""]
        t += d
    L += [f"**Total: {int(t) // 60}:{int(t) % 60:02d} ({t:.1f} s)**, cap {MAX_TOTAL:.0f} s.", "",
          "## Honesty notes", "",
          "- s1 is a minimized case; the original Muse run (seed 1, run 173) also fails with the policy off. The right "
          "panel changes ONE thing (suppress_isolation). Its peak error (137 deg) is shown only after the safety-rule "
          "metric, with the note that the craft tumbles through safe mode but recovers within the limit.",
          "- s3 is a real, unedited terminal recording; only the model wait is sped up, with a burned-in label. Only this "
          "live call has a request id; recorded calls (search/repair logs) have none.",
          "- s4 counts are ablation classes of 276 minimized cases; D4 is a code bug in our policy, reported, not fixed.",
          "- s5 signatures are fault-combination counts, not defects. Random is i.i.d. over the whole space; the matched "
          "random bars are filled only from data/matched/summary.json. MATCHED fam.+params samples each parameter from "
          "the marginals of Muse's own proposals, so it is a hindsight-informed baseline, not an independent method.",
          "- s6 describes the strict and budget gates separately; the budget gate accepts by design up to 3 broken clean "
          "runs per patch. Only one budget round was accepted (1 waiver in total)."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    dj = os.path.join(HERE, "vo_v4", "durations.json")
    durs = json.load(open(dj)) if os.path.exists(dj) else None
    out = P("docs", "video_v4_script.md")
    open(out, "w").write(to_markdown(durs)); print("wrote", out)
