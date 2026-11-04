"""Single source of truth for demo video v2: segment ids, nominal durations, on-screen visuals, voiceover text.

    python3 demo/v2_script.py        # regenerates docs/video_v2_script.md from this file

Used by demo/make_vo.py (narration) and demo/make_video_v2.py (render). A segment's real length is
max(nominal, voiceover + VO_PAD), so editing the text here and re-rendering keeps audio and picture in sync.
Lines marked pending=True contain placeholders for the gated-repair results (data/gated/, ~9 AM ET Nov 4);
update them when the results land, then re-run demo/render_v2.sh.
"""
import os

VO_LEAD, VO_PAD = 0.5, 1.0     # s of silence before narration starts in a segment / minimum tail after it
MAX_TOTAL = 178.0              # hard cap (submission limit is 3:00)

SEGMENTS = [
    dict(id="s1", name="Title: existed before / built this week", nominal=12,
         visual="Star field. 'FaultForge' + tagline. Two lines: 'Existed before: Basilisk spacecraft simulator "
                "(open source) and the Meta Muse Spark API.' / 'Built this week: fault harness, FDIR safe-mode "
                "policy, Muse-guided search, minimizer, policy on/off causal check, gated repair loop.'",
         vo="Before this week, there was Basilisk, an open-source spacecraft simulator. This week we built "
            "FaultForge, where Meta's Muse Spark hunts for failures caused by a spacecraft's own safety logic."),
    dict(id="s2", name="Credibility: the policy passes single-fault testing", nominal=17,
         visual="576-cell grid filling green/red (data/grid.jsonl) -> '568 / 576'. Footer: 'Policy structure "
                "follows published CubeSat FDIR (EUCASS 2019, NASA SWEHB 9.07, ECSS-E-ST-60-30C). Thresholds are "
                "ours.' Small spec list: torque-residual FDIR 3e-4 Nm, 1 isolation max, safe mode at 15 deg/120 s.",
         vo="Our CubeSat has four reaction wheels and fault protection built like published designs: detect a bad"
            " wheel, isolate it, fall back to safe mode. Tested one fault at a time, it passes five hundred "
            "sixty-eight of five hundred seventy-six runs. It looks safe."),
    dict(id="s3", name="Search race: Muse vs CMA-ES vs random (3 seeds)", nominal=27,
         visual="Animated cumulative-violation race, seed 1, 300 sims per arm (data/cmp/*_seed1.jsonl). Then "
                "plots/arms_comparison.png (3 seeds) with a callout row: viol/sim and sims-to-first-violation "
                "per arm (data/cmp/summary.json, or blind_3seed_prelim.json until compare.py finishes).",
         vo="But real failures stack. So we race four searchers on the same budget. Muse Spark reads every result "
            "and proposes the next fault scenarios. Muse finds its first failure in about six simulations; CMA-ES "
            "needs about a hundred. Across three seeds, a third of Muse's runs end in a safety violation. CMA-ES "
            "manages one in twelve, random under one in a hundred."),
    dict(id="s4", name="Headline replay a6e8087b: policy on vs off", nominal=33,
         visual="Split screen, Basilisk replay of minimized case a6e8087b7a52c977 (found by Muse, muse_seed1_173): "
                "3D spacecraft + boresight, event ticker, attitude-error strip with 30 deg bound, wheel speeds. "
                "Left: policy ON -> ATTITUDE LOSS (peak 180 deg). Right: policy OFF -> SURVIVES (peak 16 deg). "
                "Closing caption: 'The policy causes the failure: it spends its one isolation on the MILD wheel.'",
         vo="Here's one Muse found, minimized to just two faults. Wheel zero picks up mild friction, and the policy "
            "isolates it, spending its only isolation. About seven minutes later, wheel one dies completely. Now it can't "
            "be isolated, the controller keeps commanding a dead wheel, and the spacecraft tumbles to a hundred "
            "and eighty degrees. Same faults, policy switched off: pointing never passes sixteen degrees. "
            "The safety logic caused this failure."),
    dict(id="s5", name="Blind inference: Muse works out the hidden rule", nominal=22,
         visual="Quote card, verbatim Muse analysis from data/cmp/museblind_seed1_calls.jsonl line 5 (round 4): "
                "'FDIR isolates at most one wheel so dual derates leave a bad wheel active...' Then per-seed bars "
                "Muse vs Muse-blind viol/sim. Caption: 'Hypothesis (untested): the rules anchor informed Muse to "
                "expected failure modes.'",
         vo="And Muse didn't need the rules. In a blind run, with the policy's logic hidden, it wrote this after "
            "four rounds: FDIR isolates at most one wheel, so dual derates leave a bad wheel active. Blind Muse "
            "found more failures than informed Muse on all three seeds. Our hypothesis: knowing the rules anchors "
            "it to the failures it expects."),
    dict(id="s6", name="Repair loop with a regression gate (PLACEHOLDERS)", nominal=24, pending=True,
         visual="(a) Gate diagram: Muse patch -> replay ~3,500 stored runs -> accept only if no previously clean run "
                "breaks. (b) Strict-gate reject table from data/gated/rejects_table.md [PLACEHOLDER card until it "
                "exists]. (c) plots/gated_repair_trend.png, measured on FRESH held-out searches [PLACEHOLDER]. "
                "(d) Waiver list from data/gated/waivers.md, each broken run listed and replayable [PLACEHOLDER].",
         vo="Then Muse proposes fixes, and every patch faces a gate: replay about thirty-five hundred stored runs, "
            "and nothing that was safe may break. The gate rejected every parameter-only patch, because each one "
            "traded one failure for another. [Result of the structural and waiver rounds goes here.] Progress is "
            "measured on fresh searches, never on the gate's own test set."),
    dict(id="s7", name="Prior work and what's new", nominal=17,
         visual="Two cited boxes: 'LLM-Falsifier (arXiv 2609.20752, 2026): LLM-guided falsification of "
                "controllers' and 'NASA Orion GN&C fault-management verification'. Below: 'New here: an open-source "
                "closed loop: find -> minimize -> policy on/off causal check -> patch -> re-test, in a physics sim.'",
         vo="This builds on prior work: LLM-Falsifier falsifies controllers with language models, and NASA "
            "verifies Orion's fault management at scale. What's new is an open, closed loop: find, minimize, "
            "prove the policy is the cause, then patch and re-test."),
    dict(id="s8", name="Limits", nominal=9,
         visual="Limits slide: static Sun direction; no momentum dumping; self-written policy (structure follows "
                "published FDIR, thresholds are ours); one spacecraft model, 2-orbit runs.",
         vo="Limits: a static Sun, no momentum dumping, and a policy we wrote ourselves: published structure, our"
            " own thresholds."),
    dict(id="s9", name="Close", nominal=8,
         visual="'Find -> minimize -> explain -> repair -> re-test'. Replay command for the headline case. "
                "Repo URL. 'Basilisk · Meta Muse Spark · CMA-ES & random baselines'.",
         vo="FaultForge: find, minimize, explain, repair, re-test. Every result in this video replays from the "
            "public repo."),
]


def to_markdown(durs=None):
    durs = durs or {}
    L = ["# FaultForge demo video v2: timed script", "",
         "Generated from `demo/v2_script.py` (`python3 demo/v2_script.py`); edit there, not here.",
         "Timings: nominal seconds, or the actual rendered length if `demo/vo/durations.json` exists.",
         "Narration: `demo/make_vo.py` (edge-tts en-US-AndrewNeural, piper en_US-ryan-high fallback).",
         "Segments marked **PENDING** hold placeholders for the gated-repair results (expected ~9 AM ET Nov 4).", ""]
    t = 0.0
    for s in SEGMENTS:
        d = durs.get(s["id"], {}).get("seg_s", s["nominal"])
        m0, m1 = divmod(int(round(t)), 60), divmod(int(round(t + d)), 60)
        L += [f"## {s['id']}  {m0[0]}:{m0[1]:02d}-{m1[0]}:{m1[1]:02d}  ({d:.1f} s)  {s['name']}"
              + ("  **PENDING**" if s.get("pending") else ""), "",
              f"**On screen:** {s['visual']}", "", f"**Voiceover:** {s['vo']}", ""]
        t += d
    L += [f"**Total: {int(t) // 60}:{int(t) % 60:02d} ({t:.1f} s)**, cap {MAX_TOTAL:.0f} s.", "",
          "## Notes", "",
          "- The required opening line is in s1 (on screen and spoken).",
          "- Muse's words 'defeats' / 'evade' appear only in verbatim on-screen quotes; narration never uses them.",
          "- 'Blind finds more' is stated as a result; the reason is explicitly a hypothesis.",
          "- Before final: replace the bracketed s6 sentence with the real outcome (structural rule accepted? "
          "waiver count? fresh-search trend down?), then re-run `bash demo/render_v2.sh`."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    dj = os.path.join(here, "vo", "durations.json")
    durs = json.load(open(dj)) if os.path.exists(dj) else None
    out = os.path.join(os.path.dirname(here), "docs", "video_v2_script.md")
    open(out, "w").write(to_markdown(durs)); print("wrote", out)
