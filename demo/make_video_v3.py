"""Render FaultForge demo video v3 from repo data + demo/vo_v3 narration + the real live take.

    bash demo/render_v3.sh                 # the one command: VO (cached) -> segments -> mux -> mp4
    python3 demo/make_video_v3.py [s3 s8]  # (re)render only some segments, then re-mux

Segment ids, lengths and narration live in demo/v3_script.py (lengths: demo/vo_v3/durations.json).
  s3  real asciinema take demo/live/take1.cast (rendered to take1.mp4 by agg, real time). Only the Muse wait is
      sped up, with a burned-in label; provenance (model, response id, x-request-id) comes from the live JSON record.
  s4/s5 recorded calls, shown verbatim from data/gated/r1t1_*.json and data/cmp/museblind_seed1_calls.jsonl, each
      labelled "recorded call" with the time the file was first committed (git log --diff-filter=A).
  s8  gate beat: every count is read from data/gated/*_gate.json; data/gated/rejects_table.md and
      plots/gated_repair_trend.png are used when `gated_v2.py report` has written them, otherwise a PLACEHOLDER card.
Only two charts: s7 (coarse failure patterns per arm) and s8 (gate trend).
Output: demo/faultforge_demo_v3.mp4
"""
import re
import json, os, shutil, subprocess, sys, textwrap
from datetime import datetime, timezone
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_video as mv  # noqa: E402
import make_video_v2 as v2  # noqa: E402  (s2 credibility + s4 headline renders, helpers)
import v3_script as vs  # noqa: E402
from make_video import (plt, FPS, W, H, BG, PANEL, GRID, FG, DIM, CYAN, AMBER, ORANGE, GREY, RED, GREEN, ARM,  # noqa
                        MONO, fade, header, matplotlib)
from PIL import Image  # noqa: E402

mv.BUILD = BUILD = os.path.join(HERE, "build_v3"); os.makedirs(BUILD, exist_ok=True)
OUT = os.path.join(HERE, "faultforge_demo_v3.mp4")
P = lambda *a: os.path.join(ROOT, *a)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONTB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONTM = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def seg_durs():
    dj = os.path.join(HERE, "vo_v3", "durations.json")
    d = json.load(open(dj)) if os.path.exists(dj) else {}
    return {s["id"]: float(d.get(s["id"], {}).get("seg_s", s["nominal"])) for s in vs.SEGMENTS}


def first_commit(rel):
    """(short hash, ISO time with offset) of the commit that first added `rel`, or (None, None)."""
    out = subprocess.run(["git", "-C", ROOT, "log", "--diff-filter=A", "--format=%h %cI", "--", rel],
                         capture_output=True, text=True).stdout.strip().splitlines()
    return tuple(out[-1].split(" ", 1)) if out else (None, None)


def et(iso):
    d = datetime.fromisoformat(iso)
    return d.strftime("%Y-%m-%d %H:%M ") + ("EDT" if d.utcoffset().total_seconds() == -4 * 3600 else
                                             "EST" if d.utcoffset().total_seconds() == -5 * 3600 else d.strftime("%z"))


def J(rel):
    return json.load(open(P(rel)))


def wrap(s, n):
    return textwrap.fill(s, n)


# ------------------------------------------------------------------ s1 before / this week / impact
def s1(D, T):
    s = mv.Seg("s1"); f = s.fig
    rng = np.random.default_rng(3); sx, sy, ss = rng.random(260), rng.random(260), rng.random(260) ** 3 * 14
    impact = ("FaultForge hands an FDIR team the multi-fault combinations a test campaign would miss, "
              + vs.impact_tail)
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf(); ax = f.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.scatter(sx, (sy + 0.004 * t) % 1, s=ss, c="#9fb3c8", alpha=0.3, lw=0)
        ax.text(0.5, 0.80, "FaultForge", ha="center", fontsize=84, weight="bold", color=CYAN, alpha=fade(t, 0.1))
        a = fade(t, 0.5)
        ax.text(0.10, 0.64, "Before this week:", fontsize=28, color=DIM, weight="bold", alpha=a)
        ax.text(0.33, 0.64, "Basilisk simulator (open source) + our rule-based FDIR / safe-mode policy",
                fontsize=21, color=DIM, alpha=a)
        a = fade(t, 3.0)
        ax.text(0.10, 0.56, "This week:", fontsize=28, color=AMBER, weight="bold", alpha=a)
        ax.text(0.33, 0.56, "Muse Spark guided search · minimizer · policy on/off check · gated repair",
                fontsize=21, alpha=a)
        a = fade(t, 6.0, 0.8)
        ax.text(0.5, 0.36, wrap(impact, 62), ha="center", va="center", fontsize=34, weight="bold", color=FG,
                alpha=a, linespacing=1.4, bbox=dict(fc=PANEL, ec=AMBER, lw=2, pad=26, alpha=0.95 * a))
        ax.text(0.5, 0.08, "Meta hackathon · Push the Frontier · every number on screen is read from the repo",
                ha="center", fontsize=17, color=DIM, alpha=fade(t, 1.0))
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s2 credibility (v2 render)
def s2(D, T):
    return v2.s2(D, T)


# ------------------------------------------------------------------ s3 LIVE take (ffmpeg composition)
def _txt(name, s):
    p = os.path.join(BUILD, f"txt_{name}.txt"); open(p, "w").write(s); return p


def s3(D, T):
    ev = [json.loads(l) for l in open(vs.LIVE_CAST).read().splitlines()[1:]]
    w0 = next(t for t, _, d in ev if "chat/completions" in d or "json_mode" in d)      # request printed
    w1 = next(t for t, _, d in ev if "HTTP 200" in d)                                 # response printed
    end = ev[-1][0] + 0.15
    SPEED = 20.0
    a_len, b_len, c_len = w0 + 0.1, (w1 - w0 - 0.2) / SPEED, end - (w1 - 0.1)
    live_len = a_len + b_len + c_len
    hold = max(T - live_len, 0.5)
    lj = json.load(open(vs.LIVE_JSON)); pv = lj["provenance"]
    ts = datetime.fromisoformat(pv["ts_utc"])
    ts_et = ts.astimezone(datetime.fromisoformat("2026-11-04T00:00:00-05:00").tzinfo)
    nv = sum(bool(r.get("violated")) for r in lj["runs"])
    banner = _txt("banner", f"LIVE  ·  real `make live`, take 1 of 2  ·  recorded {ts:%Y-%m-%d %H:%M} UTC "
                            f"({ts_et:%H:%M} EST)  ·  unedited except the labelled speed-up")
    role = _txt("role", "Muse role 1: scenario search")
    sped = _txt("sped", f"SPED UP {SPEED:.0f}×  —  Muse call in progress (real wait {w1 - w0:.1f} s)")
    prov = _txt("prov", "\n".join([
        f"model            {pv['model']}   (requested {pv['model_requested']})",
        f"endpoint         {pv['endpoint']}",
        f"response id      {pv['response_id']}",
        f"{pv.get('request_id_header', 'x-request-id'):<17}{pv['request_id']}",
        f"HTTP {pv['http_status']}  latency {pv['latency_s']:.1f} s  tokens {pv['usage']['total_tokens']}",
        f"result           {nv}/{len(lj['runs'])} scenarios violated a safety constraint",
        f"record           {os.path.relpath(vs.LIVE_JSON, ROOT)}"]))
    take = os.path.join(HERE, "live", "take1.mp4")
    ff = lambda p: p.replace(":", r"\:")
    t_sp0, t_sp1, t_h = a_len, a_len + b_len, live_len
    fc = (f"[0:v]fps={FPS},split=3[x][y][z];"
          f"[x]trim=0:{a_len:.3f},setpts=PTS-STARTPTS[a];"
          f"[y]trim={w0 + 0.1:.3f}:{w1 - 0.1:.3f},setpts=(PTS-STARTPTS)/{SPEED}[b];"
          f"[z]trim={w1 - 0.1:.3f}:{end:.3f},setpts=PTS-STARTPTS[c];"
          f"[a][b][c]concat=n=3:v=1:a=0,fps={FPS},tpad=stop_mode=clone:stop_duration={hold + 1.5:.3f}[t];"
          f"color=c={BG}:s={W}x{H}:r={FPS}:d={T:.3f}[bg];"
          f"[t]scale=-2:928[ts];[bg][ts]overlay=(W-w)/2:120:shortest=1,"
          f"drawtext=fontfile={FONTB}:textfile={ff(banner)}:x=(w-tw)/2:y=20:fontsize=24:fontcolor={RED},"
          f"drawtext=fontfile={FONTB}:textfile={ff(role)}:x=(w-tw)/2:y=62:fontsize=32:fontcolor={AMBER},"
          f"drawbox=x=380:y=430:w=1160:h=120:color={BG}@0.92:t=fill:enable='between(t,{t_sp0:.3f},{t_sp1:.3f})',"
          f"drawbox=x=380:y=430:w=1160:h=120:color={AMBER}:t=4:enable='between(t,{t_sp0:.3f},{t_sp1:.3f})',"
          f"drawtext=fontfile={FONTB}:textfile={ff(sped)}:x=(w-tw)/2:y=470:fontsize=36:fontcolor={AMBER}:"
          f"enable='between(t,{t_sp0:.3f},{t_sp1:.3f})',"
          f"drawbox=x=250:y=150:w=1420:h=330:color={BG}@0.93:t=fill:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawbox=x=250:y=150:w=1420:h=330:color={CYAN}:t=3:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTB}:text='Provenance of this live call (from the JSON record it wrote)':"
          f"x=290:y=175:fontsize=26:fontcolor={CYAN}:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTM}:textfile={ff(prov)}:x=290:y=225:fontsize=24:line_spacing=10:fontcolor={FG}:"
          f"enable='gte(t,{t_h + 0.4:.3f})',format=yuv420p[v]")
    out = os.path.join(BUILD, "s3.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", take, "-filter_complex", fc, "-map", "[v]",
                    "-t", f"{T:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "20", out],
                   check=True)
    Image.open(_still(out, t_h + 1.5)).save(os.path.join(HERE, "v3_still_live.png"))
    return int(round(T * FPS))


def _still(mp4, t):
    p = os.path.join(BUILD, "still_tmp.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", mp4, "-frames:v", "1", p], check=True)
    return p


# ------------------------------------------------------------------ s4 recorded calls: diagnosis + patch + gate
def card(f, x, y, w, h, ec, a, lw=2):
    f.add_artist(matplotlib.patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006", fc=PANEL, ec=ec, lw=lw,
                                                   alpha=a, transform=f.transFigure))


def s4(D, T):
    s = mv.Seg("s4", {int(0.8 * T * FPS): "v3_still_recorded.png"}); f = s.fig
    r = J("data/gated/r1t1_response.json"); g = J("data/gated/r1t1_gate.json"); p = r["parsed"]
    h, iso = first_commit("data/gated/r1t1_response.json")
    rec = (f"recorded call · {r['model']} · latency {float(r['latency_s']):.1f} s · first committed {et(iso)} "
           f"(commit {h}) · request id was not logged for repair calls") if h else "recorded call (not yet committed)"
    gd = g["gate"]
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Muse roles 2 and 3: diagnosis, then a patch proposal", rec,
               "data/gated/r1t1_response.json (verbatim) · data/gated/r1t1_gate.json (computed by the gate, not Muse)")
        a = fade(t, 0.3)
        card(f, 0.04, 0.40, 0.44, 0.44, AMBER, a)
        f.text(0.06, 0.80, "ROLE 2 · DIAGNOSIS  (Muse, verbatim)", fontsize=20, weight="bold", color=AMBER, alpha=a)
        f.text(0.06, 0.765, wrap("“" + p["diagnosis"] + "”", 58), fontsize=17, va="top", alpha=a, linespacing=1.4,
               style="italic")
        b = fade(t, 0.30 * T)
        card(f, 0.52, 0.40, 0.44, 0.44, ORANGE, b)
        f.text(0.54, 0.80, "ROLE 3 · PATCH PROPOSAL  (Muse, verbatim)", fontsize=20, weight="bold", color=ORANGE,
               alpha=b)
        f.text(0.54, 0.755, json.dumps(p["change"]), fontsize=22, family=MONO, color=FG, va="top", alpha=b)
        f.text(0.54, 0.69, wrap("“" + textwrap.shorten(p["rationale"], 330, placeholder=" …") + "”", 58), fontsize=16,
               va="top", alpha=b, linespacing=1.4, style="italic", color=DIM)
        c = fade(t, 0.55 * T)
        card(f, 0.04, 0.10, 0.92, 0.24, RED, c, 3)
        f.text(0.06, 0.29, "GATE DECISION  (code, outside the model's control)", fontsize=20, weight="bold",
               color=RED, alpha=c)
        f.text(0.06, 0.22, g["decision"].upper(), fontsize=46, weight="bold", color=RED, alpha=c)
        f.text(0.26, 0.235, re.sub(r"\s*\(evaluation stopped early after \d+ runs\)", " · stopped early", g["gate_reason"]), fontsize=19, family=MONO, alpha=c)
        f.text(0.26, 0.185, f"fixes {gd['fixes']} · runs with new violations {gd['runs_with_new_violations']} "
                            f"(previously clean {gd['clean_to_violating']}) · evaluated {gd['evaluated']} runs",
               fontsize=17, family=MONO, color=DIM, alpha=c)
        f.text(0.26, 0.135, "the rejection and its regressions go back into Muse's next prompt", fontsize=17,
               color=DIM, alpha=c)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s5 recorded call: blind inference
def s5(D, T):
    s = mv.Seg("s5", {int(0.6 * T * FPS): "v3_still_blind.png"}); f = s.fig
    rel = "data/cmp/museblind_seed1_calls.jsonl"
    c = json.loads(open(P(rel)).read().splitlines()[4]); q = c["analysis"]
    first = q.split(". ")[0] + "."; rest = q[len(first):].strip()
    h, iso = first_commit(rel)
    rec = (f"recorded call · round {c.get('round')} · latency {float(c['latency_s']):.1f} s · first committed {et(iso)} "
           f"(commit {h})") if h else "recorded call"
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Rules-blind: Muse works out the hidden rule", rec, f"{rel} line 5, field 'analysis' · src/ff_sim.py")
        a = fade(t, 0.3)
        f.text(0.06, 0.80, "The prompt had NO thresholds and NO isolation limit; only per-run outcomes came back.",
               fontsize=20, color=DIM, alpha=a)
        f.text(0.06, 0.72, "Muse Spark, verbatim:", fontsize=20, color=DIM, alpha=a)
        f.text(0.06, 0.67, wrap("“" + first + "”", 40), fontsize=40, weight="bold", color=AMBER, va="top", alpha=a,
               linespacing=1.35, style="italic")
        f.text(0.06, 0.46, wrap("“… " + rest + "”", 70), fontsize=18, color=DIM, va="top", alpha=a, linespacing=1.4,
               style="italic")
        b = fade(t, 0.45 * T)
        card(f, 0.62, 0.14, 0.34, 0.20, GREEN, b)
        f.text(0.64, 0.29, "Ground truth (src/ff_sim.py)", fontsize=19, weight="bold", color=GREEN, alpha=b)
        f.text(0.64, 0.24, "FDIR isolates at most ONE wheel", fontsize=21, family=MONO, alpha=b)
        f.text(0.64, 0.19, "(keeps 3 wheels for 3-axis control)", fontsize=17, color=DIM, alpha=b)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s6 headline (v2 s4 render reused)
def s6(D, T):
    src = os.path.join(HERE, "build_v2", "s4.mp4"); dst = os.path.join(BUILD, "s6.mp4")
    ok = os.path.exists(src) and abs(float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", src])) - T) < 0.05
    if ok:
        shutil.copyfile(src, dst); return int(round(T * FPS))
    n = v2.s4(D, T)                      # renders build_v3/s4.mp4 (mv.BUILD) -> rename
    os.replace(os.path.join(BUILD, "s4.mp4"), dst)
    return n


# ------------------------------------------------------------------ s7 chart 1: coarse patterns per arm
def s7(D, T):
    s = mv.Seg("s7", {int(0.85 * T * FPS): "v3_still_patterns.png"}); f = s.fig
    S = J("data/cmp/summary.json")["arms"]; arms = ["museblind", "muse", "cmaes", "random"]
    per = {a: [S[a]["per_seed"][k]["unique_patterns_coarse"] for k in ("0", "1", "2")] for a in arms}
    mean = {a: S[a]["mean"]["unique_patterns_coarse"] for a in arms}
    first = {a: S[a]["mean"]["sims_to_first_violation"] for a in arms}
    sims = [S["muse"]["per_seed"][k]["sims"] for k in ("0", "1", "2")]
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Distinct failure patterns found, per arm", f"3 seeds · equal simulation budget per seed "
               f"({' / '.join(map(str, sims))} sims) · coarse pattern = set of violated constraints × fault types",
               "data/cmp/summary.json (unique_patterns_coarse, sims_to_first_violation)")
        g = np.clip((t - 0.4) / 1.6, 0, 1)
        ax = f.add_axes([0.08, 0.20, 0.60, 0.62]); ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
        xs = np.arange(len(arms))
        ax.bar(xs, [mean[a] * g for a in arms], 0.6, color=[ARM[a][1] for a in arms])
        for k, a in enumerate(arms):
            ax.plot([k - 0.12, k, k + 0.12], np.array(per[a]) * g, "o", color=FG, ms=8, alpha=g)
            if g > 0.98:
                ax.text(k, max(max(per[a]), mean[a]) + 1.0, f"{mean[a]:.1f}", ha="center", fontsize=22, weight="bold", color=ARM[a][1])
        ax.set_xticks(xs); ax.set_xticklabels([ARM[a][0] for a in arms], fontsize=20)
        ax.set_ylim(0, 27); ax.set_ylabel("distinct coarse failure patterns (mean; dots = seeds)", fontsize=15)
        ax.tick_params(axis="y", labelsize=13)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        a = fade(t, 0.45 * T)
        f.text(0.72, 0.78, "first violation after", fontsize=22, color=DIM, alpha=a)
        for k, ar in enumerate(arms):
            f.text(0.72, 0.70 - k * 0.075, ARM[ar][0], fontsize=24, color=ARM[ar][1], weight="bold", alpha=a)
            f.text(0.95, 0.70 - k * 0.075, f"~{first[ar]:.0f} sims", fontsize=24, family=MONO, color=ARM[ar][1],
                   ha="right", alpha=a)
        f.text(0.72, 0.33, wrap("mean over seeds 0-2. Muse: rules in the prompt. Muse-blind: rules hidden. "
                                "CMA-ES: evolutionary optimizer on a safety-margin objective. random: uniform.", 40),
               fontsize=15, color=DIM, va="top", linespacing=1.45, alpha=a)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s8 gate beat + chart 2 (auto-filled)
def gate_rows():
    rows = []
    for g in vs.GF["all"]:
        r = g["reason"].replace("rejected (strict): ", "").replace("rejected: ", "").replace("accepted (budget): ", "").replace("rejected (budget): ", "")
        rows.append((g["name"], g["phase"], g["decision"], textwrap.shorten(r, 92, placeholder="…")))
    return rows


def s8(D, T):
    s = mv.Seg("s8", {int(0.45 * T * FPS): "v3_still_gate.png"}); f = s.fig
    rej, trend = P("data/gated/rejects_table.md"), P("plots/gated_repair_trend.png")
    trend_img = np.asarray(Image.open(trend).convert("RGB")) if os.path.exists(trend) else None
    rows = gate_rows(); GF = vs.GF
    n_r = sum(g["phase"] == "strict" for g in GF["all"]); n_s = sum(g["phase"] == "structural" for g in GF["all"])
    t1, t2 = 0.30 * T, 0.66 * T
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        if t < t1:
            header(f, "Repairs face checks outside the model's control",
                   "Every Muse patch is re-simulated on all 3,508 stored runs; the gate's code decides",
                   "src/gated_repair.py · src/gated_v2.py")
            steps = [("Muse proposes\na policy patch", ORANGE), ("re-simulate\n3,508 stored runs", CYAN),
                     ("gate decides\n(code, not Muse)", GREEN), ("rejection + regressions\nfed back to Muse", AMBER)]
            for k, (txt, col) in enumerate(steps):
                a = fade(t, 0.2 + 0.5 * k); x = 0.05 + k * 0.235
                card(f, x, 0.50, 0.20, 0.20, col, a, 2.5)
                f.text(x + 0.10, 0.60, txt, fontsize=21, ha="center", va="center", alpha=a)
                if k < 3:
                    f.text(x + 0.217, 0.60, "→", fontsize=40, color=DIM, ha="center", va="center", alpha=a)
            a = fade(t, 2.4)
            f.text(0.05, 0.38, "True retry budgets:", fontsize=24, weight="bold", color=FG, alpha=a)
            f.text(0.05, 0.32, "strict loop: up to 6 proposals per round (4 tries + 2 narrow)  ·  "
                               "budget mode: up to 4 per round", fontsize=21, family=MONO, alpha=a)
            f.text(0.05, 0.25, "strict: 0 previously clean runs may break  ·  budget: net fixes > 0 and "
                               "≤ 3 clean runs (0.1%) may break, each one a declared waiver", fontsize=18, color=DIM,
                   alpha=a)
        elif t < t2:
            header(f, "Every proposal so far, and what the gate decided",
                   f"strict {n_r} · structural {n_s} · budget {GF['n_bud']}  ·  accepted: "
                   f"{', '.join(GF['acc']) or 'none'}",
                   "data/gated/*_gate.json" + (" · data/gated/rejects_table.md" if os.path.exists(rej) else ""))
            a = fade(t, t1)
            f.text(0.05, 0.82, f"{'name':6s} {'phase':11s} {'decision':9s} gate reason", fontsize=16, family=MONO,
                   color=DIM, weight="bold", alpha=a)
            for k, (n, ph, dcs, r) in enumerate(rows[:14]):
                col = GREEN if dcs == "accept" else FG
                f.text(0.05, 0.78 - k * 0.046, f"{n:6s} {ph:11s} {dcs.upper():9s} {r}", fontsize=15, family=MONO,
                       color=col, weight="bold" if dcs == "accept" else "normal", alpha=a)
            if len(rows) > 14:
                f.text(0.05, 0.78 - 14 * 0.046, f"… {len(rows) - 14} more in data/gated/", fontsize=15, color=DIM,
                       alpha=a)
        else:
            header(f, "Gate trend across repair rounds", "written by `gated_v2.py report`",
                   "plots/gated_repair_trend.png")
            a = fade(t, t2)
            if trend_img is not None:
                h_, w_ = trend_img.shape[:2]; ww = min(0.9, 0.74 * (w_ / h_) * H / W)
                axi = f.add_axes([0.5 - ww / 2, 0.10, ww, 0.74]); axi.imshow(trend_img, alpha=a); axi.set_axis_off()
            else:
                v2.placeholder(f, 0.15, 0.25, 0.70, 0.5, "gate trend chart (auto-filled on re-render)",
                               "plots/gated_repair_trend.png", a)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s9 prior work + limits
def s9(D, T):
    s = mv.Seg("s9"); f = s.fig
    boxes = [("LLM-Falsifier", "arXiv 2609.20752 (2026)", "LLM-guided falsification of controllers"),
             ("NASA Orion GN&C", "fault-management verification", "large-scale FM verification campaigns")]
    lim = ["static Sun direction over a run", "no momentum dumping (no magnetorquers)",
           "thresholds are ours (structure follows published FDIR, docs/fdir_refs.md)",
           "one spacecraft model, 2-orbit runs"]
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Prior work, what is new, and limits", None, "README.md · docs/fdir_refs.md")
        for k, (a1, a2, a3) in enumerate(boxes):
            a = fade(t, 0.2 + 0.5 * k); x = 0.05 + k * 0.46
            card(f, x, 0.62, 0.43, 0.20, GRID, a, 1.5)
            f.text(x + 0.02, 0.77, a1, fontsize=28, weight="bold", color=CYAN, alpha=a)
            f.text(x + 0.02, 0.72, a2, fontsize=17, color=DIM, alpha=a)
            f.text(x + 0.02, 0.66, a3, fontsize=19, alpha=a)
        a = fade(t, 0.30 * T)
        f.text(0.05, 0.53, "New here:", fontsize=24, weight="bold", color=AMBER, alpha=a)
        f.text(0.19, 0.53, "an open, closed loop (find · minimize · policy on/off · patch · re-test) in a physics sim",
               fontsize=22, alpha=a)
        b = fade(t, 0.55 * T)
        f.text(0.05, 0.43, "Limits:", fontsize=24, weight="bold", color=RED, alpha=b)
        for k, it in enumerate(lim):
            f.text(0.19, 0.43 - k * 0.07, "·  " + it, fontsize=22, alpha=fade(t, 0.55 * T + 0.3 * k))
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s10 close
def s10(D, T):
    s = mv.Seg("s10"); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf(); ax = f.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        a = fade(t, 0.1)
        ax.text(0.5, 0.68, "FaultForge", fontsize=80, ha="center", weight="bold", color=CYAN, alpha=a)
        ax.text(0.5, 0.48, f"git clone https://{v2.REPO_URL}  &&  make replay", fontsize=30, family=MONO,
                ha="center", color=GREEN, alpha=fade(t, 0.5),
                bbox=dict(fc=PANEL, ec=GRID, lw=1.5, pad=20, alpha=fade(t, 0.5)))
        ax.text(0.5, 0.35, "no API key needed  ·  `make live` with MUSE_API_KEY for a fresh Muse round", fontsize=22,
                ha="center", color=DIM, alpha=fade(t, 1.0))
        s.frame()
    return s.close()


SEGS = dict(s1=s1, s2=s2, s3=s3, s4=s4, s5=s5, s6=s6, s7=s7, s8=s8, s9=s9, s10=s10)
assert list(SEGS) == [s["id"] for s in vs.SEGMENTS]


def _run(k):
    T = seg_durs()[k]
    D = v2.load_data() if k in ("s2", "s6") else {}
    return k, SEGS[k](D, T)


def mux(durs):
    ids = list(SEGS); vids = [os.path.join(BUILD, f"{k}.mp4") for k in ids]
    inputs, parts = [], []
    for n, (k, v) in enumerate(zip(ids, vids)):
        inputs += ["-i", v]
        parts.append(f"[{n}:v]fps={FPS},scale={W}:{H},setsar=1,format=yuv420p,trim=0:{durs[k]:.3f},"
                     f"setpts=PTS-STARTPTS[v{n}]")
    m = len(ids)
    for n, k in enumerate(ids):
        wav = os.path.join(HERE, "vo_v3", f"{k}.wav"); T = durs[k]
        if os.path.exists(wav):
            inputs += ["-i", wav]
            parts.append(f"[{m + n}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                         f"adelay={int(vs.VO_LEAD * 1000)}:all=1,apad,atrim=0:{T:.3f},asetpts=PTS-STARTPTS[a{n}]")
        else:
            inputs += ["-f", "lavfi", "-t", f"{T:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            parts.append(f"[{m + n}:a]atrim=0:{T:.3f}[a{n}]")
    fc = ";".join(parts) + ";" + "".join(f"[v{n}][a{n}]" for n in range(m)) + f"concat=n={m}:v=1:a=1[vo][ao]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[vo]", "-map", "[ao]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-b:a", "160k", "-movflags", "+faststart", OUT], check=True)
    d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                       "default=nw=1:nk=1", OUT]).decode())
    print(f"wrote {OUT}  {d:.2f} s ({int(d) // 60}:{int(d) % 60:02d})")
    assert d <= vs.MAX_TOTAL + 0.5, f"video is over the {vs.MAX_TOTAL:.0f} s cap"


if __name__ == "__main__":
    durs = seg_durs(); tot = sum(durs.values())
    print("segments:", {k: round(v, 1) for k, v in durs.items()}, f"total {tot:.1f} s")
    assert tot <= vs.MAX_TOTAL, f"total {tot:.1f} s exceeds cap"
    only = [a for a in sys.argv[1:] if a in SEGS] or list(SEGS)
    only = sorted(only, key=lambda k: -durs[k])
    with Pool(min(len(only), int(os.environ.get("FF_RENDER_WORKERS", "2")))) as p:
        for name, n in p.imap_unordered(_run, only):
            print(name, n, "frames", round(n / FPS, 1), "s", flush=True)
    mux(durs)
