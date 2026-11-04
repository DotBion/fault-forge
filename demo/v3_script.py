"""Single source of truth for demo video v3: segment ids, nominal durations, on-screen visuals, voiceover text.

    python3 demo/v3_script.py        # regenerates docs/video_v3_script.md from this file
    bash demo/render_v3.sh           # narration (demo/vo_v3/) -> render -> demo/faultforge_demo_v3.mp4

Gate facts in the narration (how many proposals, how many rejected, whether any patch was accepted) are COUNTED from
data/gated/*_gate.json when this module is imported, so re-rendering after the repair pipeline finishes keeps the
spoken numbers true. The live beat uses the real asciinema take demo/live/take1.cast (see demo/record_live.sh).
"""
import glob, json, os

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
VO_LEAD, VO_PAD = 0.5, 0.7     # s of silence before narration in a segment / minimum tail after it
MAX_TOTAL = 175.0              # hard cap 2:55
LIVE_CAST = os.path.join(HERE, "live", "take1.cast")
LIVE_JSON = os.path.join(ROOT, "data", "live", "live_2026-11-04T061215Z.json")   # written by that same take

NUM = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
       10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
       17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty"}
say = lambda n: NUM.get(n, str(n))


def gate_facts():
    G = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "gated", "*_gate.json"))):
        g = json.load(open(p)); n = g.get("name") or os.path.basename(p)[:-10]
        ph = g.get("phase") or ("strict" if n.startswith("r") else "structural" if n.startswith("s") else "budget")
        G.append(dict(name=n, phase=ph, decision=g.get("decision"), reason=g.get("gate_reason", "")))
    sx = [g for g in G if g["phase"] in ("strict", "structural")]
    bud = [g for g in G if g["phase"] == "budget"]
    return dict(all=G, n_sx=len(sx), n_sx_rej=sum(g["decision"] == "reject" for g in sx), n_bud=len(bud),
                bud_acc=[g["name"] for g in bud if g["decision"] == "accept"],
                acc=[g["name"] for g in G if g["decision"] == "accept"])


GF = gate_facts()
ACCEPTED = bool(GF["acc"])


def live_facts():
    if not os.path.exists(LIVE_JSON):
        return dict(lat=None, nv=None, n=None)
    d = json.load(open(LIVE_JSON))
    prov = d.get("provenance") or d.get("prov") or {}
    res = d.get("runs") or []
    nv = sum(bool(r.get("violated")) for r in res) if res else d.get("n_violated")
    return dict(lat=prov.get("latency_s"), nv=nv, n=len(res) or None)


LF = live_facts()

def _gate(name):
    g = json.load(open(os.path.join(ROOT, "data", "gated", f"{name}_gate.json")))["gate"]
    return g if isinstance(g, dict) else {}


_sx_rej_all = GF["n_sx"] and GF["n_sx_rej"] == GF["n_sx"]
gate_result = (f"All {say(GF['n_sx'])} strict and structural proposals failed, each adding new violations."
               if _sx_rej_all else f"{say(GF['n_sx'] - GF['n_sx_rej'])} of {say(GF['n_sx'])} strict and structural "
               "proposals passed.")
if GF["bud_acc"]:
    _g = _gate(GF["bud_acc"][0]); _c = int(_g.get("clean_to_violating", -1))
    gate_result += (f" Then a budget-mode patch passed: {say(int(_g.get('fixes', 0)))} fixes, " +
                    ("no clean run broken." if _c == 0 else f"{say(_c)} clean runs broken, each listed as a waiver."))
elif GF["n_bud"]:
    gate_result += f" Budget mode has tried {say(GF['n_bud'])} so far, none accepted."
else:
    gate_result += " Budget-mode results are pending."
# the owner's impact line claims a vetted patch: only say it when the gate has really accepted one
impact_tail = ("each as a one-command replay, with a candidate patch the gate has vetted." if ACCEPTED else
               "each as a one-command replay, with every candidate patch checked by a regression gate.")
if LF["nv"] is not None and LF["n"]:
    live_result = f"Basilisk simulates all {say(LF['n'])}: {say(LF['nv'])} break a safety rule."
else:
    live_result = "Basilisk then simulates each one."

SEGMENTS = [
    dict(id="s1", name="Before this week / this week / impact", nominal=15,
         visual="Title. 'Before this week: Basilisk (open source) + our rule-based FDIR policy.' 'This week: Muse-guided "
                "search, minimizer, policy on/off check, gated repair loop.' Impact line on screen.",
         vo="Before this week: Basilisk and a rule-based FDIR policy. This week: Muse-guided search and "
            "gated repair. FaultForge hands an FDIR team the multi-fault combinations a test "
            "campaign would miss, " + impact_tail),
    dict(id="s2", name="Credibility: 568/576", nominal=11,
         visual="576-cell single-fault grid filling in -> '568 / 576'. Policy rules listed; 'structure follows published "
                "CubeSat FDIR, thresholds are ours'.",
         vo="Four reaction wheels, published-style fault protection. Tested one fault at a time, "
            "it passes five hundred sixty-eight of five hundred seventy-six runs."),
    dict(id="s3", name="LIVE: make live (Muse role 1, scenario search)", nominal=22,
         visual="Real asciinema take demo/live/take1.cast, unedited; banner 'LIVE · recorded <UTC/ET>'. The Muse wait is "
                "played faster with a burned-in 'SPED UP Nx' label; everything else real time; final frame held with "
                "a provenance callout (model, response id, x-request-id, latency).",
         vo="This is a live, unedited run. Role one, scenario search: Muse Spark reads the policy and returns eight "
            "fault scenarios as structured JSON. The wait for the model is shown sped up, and labeled. " + live_result +
            " Every live call logs its model id and request id."),
    dict(id="s4", name="Recorded calls: Muse roles 2 and 3 (diagnosis, patch proposal) + gate decision", nominal=16,
         visual="Cards built verbatim from data/gated/r1t1_*.json and s1_*.json: diagnosis -> proposed patch JSON -> gate "
                "decision (computed by code). Label 'recorded call, first committed <ET>'; 'request id not logged'.",
         vo="Roles two and three, from recorded calls. Muse diagnoses the minimized failures: the policy spends its only "
            "isolation on the first, mild fault. Then it proposes a patch, and the gate, not the model, decides."),
    dict(id="s5", name="Recorded call: rules-blind inference", nominal=12,
         visual="Quote card, verbatim, data/cmp/museblind_seed1_calls.jsonl line 5 (round 4); 'recorded call, first "
                "committed <ET>'; ground truth shown beside it.",
         vo="With the policy hidden from the prompt, blind Muse inferred the rule after four rounds: FDIR isolates at "
            "most one wheel, so dual derates leave a bad wheel active."),
    dict(id="s6", name="Headline a6e8087b: policy on vs off (same render as v2 s4)", nominal=33,
         visual="Split-screen Basilisk replay of a6e8087b7a52c977: policy ON -> attitude loss (peak 180 deg); policy OFF "
                "-> survives (peak 16 deg).",
         vo="Here's one Muse found, minimized to just two faults. Wheel zero picks up mild friction, and the policy "
            "isolates it, spending its only isolation. About seven minutes later, wheel one dies completely. Now it can't "
            "be isolated, the controller keeps commanding a dead wheel, and the spacecraft tumbles to a hundred "
            "and eighty degrees. Same faults, policy switched off: pointing never passes sixteen degrees. "
            "The safety logic caused this failure."),
    dict(id="s7", name="Chart 1: distinct coarse failure patterns per arm (3 seeds)", nominal=15,
         visual="Bar chart: unique COARSE failure patterns per seed (mean + per-seed dots) for Muse-blind, Muse, CMA-ES, "
                "random from data/cmp/summary.json; sims-to-first-violation under each bar.",
         vo="Over three seeds with equal budgets, both Muse arms find about twenty failure patterns; CMA-ES "
            "about two, random about one. Muse's first failure comes in about six simulations, CMA-ES's in "
            "about a hundred."),
    dict(id="s8", name="Gate: checks outside the model's control; chart 2 trend (auto-filled)", nominal=24, pending=True,
         visual="Gate diagram (patch -> re-simulate 3,508 runs -> decision -> rejection + regressions back to Muse), the "
                "true retry budgets, reject table (data/gated/rejects_table.md or the gate files), trend chart "
                "plots/gated_repair_trend.png [PLACEHOLDER until it exists].",
         vo="Repairs face checks outside the model's control. Each Muse patch is re-simulated on thirty-five hundred "
            "stored runs, and each rejection, with its regressions, goes back to Muse: up to six proposals per round "
            "strict, four in budget mode. " + gate_result),
    dict(id="s9", name="Prior work + limits", nominal=13,
         visual="Prior work boxes (LLM-Falsifier, NASA Orion GN&C FM verification) + 'new here'; limits list.",
         vo="This builds on LLM-Falsifier and NASA's Orion fault-management verification. New here is an open, closed "
            "loop in a physics sim. Limits: a static Sun, no momentum dumping, and thresholds we chose."),
    dict(id="s10", name="Close", nominal=5,
         visual="'git clone … && make replay' (no key) / 'make live' (your key). Repo URL.",
         vo="FaultForge. Clone it and run make replay. No key needed."),
]


def to_markdown(durs=None):
    durs = durs or {}
    L = ["# FaultForge demo video v3: timed script", "",
         "Generated from `demo/v3_script.py` (`python3 demo/v3_script.py`); edit there, not here.",
         "Timings: nominal seconds, or the rendered length if `demo/vo_v3/durations.json` exists.",
         "Narration: `demo/make_vo.py --script v3` (edge-tts en-US-AndrewNeural, piper fallback).",
         f"Gate facts counted from data/gated at generation time: {GF['n_sx']} strict/structural proposals "
         f"({GF['n_sx_rej']} rejected), {GF['n_bud']} budget-mode proposals, accepted: {GF['acc'] or 'none'}.", ""]
    t = 0.0
    for s in SEGMENTS:
        d = durs.get(s["id"], {}).get("seg_s", s["nominal"])
        m0, m1 = divmod(int(round(t)), 60), divmod(int(round(t + d)), 60)
        L += [f"## {s['id']}  {m0[0]}:{m0[1]:02d}-{m1[0]}:{m1[1]:02d}  ({d:.1f} s)  {s['name']}"
              + ("  **AUTO-FILLED**" if s.get("pending") else ""), "",
              f"**On screen:** {s['visual']}", "", f"**Voiceover:** {s['vo']}", ""]
        t += d
    L += [f"**Total: {int(t) // 60}:{int(t) % 60:02d} ({t:.1f} s)**, cap {MAX_TOTAL:.0f} s.", "",
          "## Honesty notes", "",
          "- s3 is a real, unedited terminal recording; only the model wait is played faster and it carries a burned-in "
          "'SPED UP Nx' label. Take 2 (demo/live/take2.cast) found 0/8 violations; it is in the repo too.",
          "- s4/s5 are recorded calls, labelled with the commit time the file was first committed; their request ids "
          "were not logged (logging was added in src/muse_client.py afterwards).",
          "- The impact line only says 'a candidate patch the gate has vetted' once a gate file records an accept; "
          "until then it says every candidate patch is checked by the gate."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    dj = os.path.join(HERE, "vo_v3", "durations.json")
    durs = json.load(open(dj)) if os.path.exists(dj) else None
    out = os.path.join(ROOT, "docs", "video_v3_script.md")
    open(out, "w").write(to_markdown(durs)); print("wrote", out)
