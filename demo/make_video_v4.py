"""Render FaultForge demo video v4 from repo data + demo/vo_v4 narration + the real live take.

    bash demo/render_v4.sh                 # the one command: VO (cached) -> segments -> mux -> mp4
    python3 demo/make_video_v4.py [s1 s6]  # (re)render only some segments, then re-mux

Segment ids, lengths and narration live in demo/v4_script.py (lengths: demo/vo_v4/durations.json).
  s1  minimized case a6e8087b: Basilisk split replay, full v1 policy vs the SAME policy with only isolation suppressed
      (demo/data/hl4_*.csv from demo/replay_causal_v4.py); end card leads with the safety-rule metric
      (data/satfix/causal_replay.json, causal_sweep.json), the 137 deg peak only shown with that context.
  s3  real asciinema take demo/live/take1.cast; only the Muse wait is sped up, with a burned-in label.
  s4  defect classes from data/satfix/defects.json (+ tie-break count via src/defects.py).
  s0  narration-only opening (problem framing) over a dimmed Ken-Burns of the s1 replay still + title.
  s3  ends on 'Muse proposed N tests -> sim found K failures' (counted from the live JSON) + provenance footer.
  s5  chart 1: exactly 4 bars (random, one-shot Muse bank, closed-loop Muse, marginals-matched random); others footnoted.
  s6  repair: held-out paired result first, then strict vs budget gate with net = fixes - runs with new violations.
  s7  three limits + 'More in README'.
One chart (s5); the unpaired fresh-search numbers are README-only. v3 files are untouched; this writes demo/build_v4/ (not committed) and the mp4.
Output: demo/faultforge_demo_v4.mp4
"""
import json, os, subprocess, sys, textwrap
from datetime import datetime
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_video as mv  # noqa: E402
import make_video_v2 as v2  # noqa: E402  (helpers only; nothing from v2 is rendered)
import v4_script as vs  # noqa: E402
from make_video import (plt, FPS, W, H, BG, PANEL, GRID, FG, DIM, CYAN, AMBER, ORANGE, GREY, RED, GREEN, ARM,  # noqa
                        MONO, fade, header, matplotlib, draw_sc, hms)
from PIL import Image  # noqa: E402

mv.BUILD = BUILD = os.path.join(HERE, "build_v4"); os.makedirs(BUILD, exist_ok=True)
OUT = os.path.join(HERE, "faultforge_demo_v4.mp4")
P = lambda *a: os.path.join(ROOT, *a)
FONTB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONTM = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
STILL = lambda n: f"v4_still_{n}.png"


def seg_durs():
    dj = os.path.join(HERE, "vo_v4", "durations.json")
    d = json.load(open(dj)) if os.path.exists(dj) else {}
    return {s["id"]: float(d.get(s["id"], {}).get("seg_s", s["nominal"])) for s in vs.SEGMENTS}


def card(f, x, y, w, h, ec, a, lw=2, z=1):
    f.add_artist(matplotlib.patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006", fc=PANEL, ec=ec, lw=lw,
                                                   alpha=a, transform=f.transFigure, zorder=z))


# ------------------------------------------------------------------ s1 minimized case: full vs isolation suppressed
def short4(msg):
    if msg.startswith("FAULT"):
        d = json.loads(msg[msg.index("{"):])
        return f"FAULT  RW{d['wheel']} {d['type']} sev {d['severity']:.2f}", AMBER
    if "SUPPRESSED" in msg:
        w = msg.split("wheel ")[1].split()[0]
        return f"FDIR   would isolate RW{w}: SUPPRESSED", GREY
    if "isolated" in msg:
        w = msg.split("wheel ")[1].split()[0]
        return f"FDIR   isolates RW{w}  (its only isolation)", CYAN
    if "-> SAFE" in msg:
        return "POLICY -> SAFE MODE", ORANGE
    if "-> NOMINAL" in msg:
        return "POLICY -> NOMINAL", GREEN
    return msg[:44], FG


def events4(run, cfg):
    ev = [(t, *short4(m)) for t, m in run["policy_log"]]
    for k, tv in run["violations"].items():
        ev.append((tv, f"VIOLATION {k}", RED))
    return sorted(ev)


def s1(D, T):
    cfg = mv.ff_sim.CFG
    hl = json.load(open(os.path.join(HERE, "data", "hl4_runs.json"))); assert hl["key"] == vs.HL_KEY
    tel = {t: pd.read_csv(os.path.join(HERE, "data", f"hl4_{t}.csv")) for t in ("full", "no_isolate")}
    C = vs.CF["c"]["results"]; ck = next(k for k in C if "minimized" in k); R = C[ck]
    sw = vs.CF["sw"]; nsw = len(sw)
    sf = sum(bool(x["full"]) for x in sw); sn = sum(bool(x["no_isolate"]) for x in sw)
    lim = cfg["att_err_max_dur_s"]
    s = mv.Seg("s1", {int(0.55 * T * FPS): STILL("s1_mid"), int((T - 0.6) * FPS): STILL("s1_end")}); f = s.fig
    runs = [("full", "FULL v1 POLICY"), ("no_isolate", "SAME POLICY, ONLY ISOLATION SUPPRESSED")]
    Tend = float(tel["full"].t_s.max())
    T_OP = 0.0                                             # the problem framing is its own segment (s0)
    T0, T1 = T_OP + 1.6, T - 9.5
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        if t < T_OP:
            a = fade(t, 0.0, 0.4) * (1 - fade(t, T_OP - 0.5))
            f.text(0.5, 0.60, "A spacecraft's own recovery logic can turn a\nsurvivable fault combination into a lost one.",
                   fontsize=44, ha="center", va="center", weight="bold", color=FG, alpha=a, linespacing=1.4)
            f.text(0.5, 0.38, "FaultForge finds those cases.", fontsize=40, ha="center", va="center", weight="bold",
                   color=AMBER, alpha=a)
            f.text(0.5, 0.22, "Basilisk spacecraft simulation  ·  Muse Spark-guided search  ·  gated repair",
                   fontsize=20, ha="center", color=DIM, alpha=a)
            s.frame(); continue
        header(f, f"A minimized case Muse found: {hl['key'][:8]}",
               "2 faults: RW0 friction 0.2 @105 s, RW1 dead @505 s · Basilisk, 2 orbits · minimized from Muse seed 1, run 173",
               "demo/data/hl4_{full,no_isolate}.csv (demo/replay_causal_v4.py) · data/satfix/causal_replay.json, "
               "causal_sweep.json")
        st = Tend * np.clip((t - T0) / (T1 - T0), 0, 1)
        f.text(0.96, 0.935, hms(st), fontsize=34, family=MONO, ha="right", color=CYAN)
        f.text(0.96, 0.898, f"sim time  ×{Tend / (T1 - T0):.0f}", fontsize=15, family=MONO, ha="right", color=DIM)
        for c, (tag, ttl) in enumerate(runs):
            d = tel[tag]; run = hl[tag]; ev = events4(run, cfg)
            j = max(int(np.searchsorted(d.t_s.values, st, side="right")) - 1, 0)
            row = d.iloc[j]; x0 = 0.04 + c * 0.48
            f.text(x0, 0.835, ttl, fontsize=20, weight="bold", color=FG)
            iso = [k for k in range(4) if row[f"rw{k}_avail"] == 0]
            f.text(x0, 0.805, f"mode {'SAFE' if row.safe_mode else 'NOMINAL':<8s} isolated "
                              f"{('RW' + ','.join(map(str, iso))) if iso else '-':<6s} att err {row.att_err_deg:5.1f}°",
                   fontsize=15, family=MONO, color=ORANGE if row.safe_mode else DIM)
            ax3 = f.add_axes([x0 - 0.01, 0.47, 0.20, 0.32], projection="3d"); ax3.set_facecolor(BG)
            sg = [row.sBR1, row.sBR2, row.sBR3]
            draw_sc(ax3, [0, 0, 0] if np.any(np.isnan(sg)) else sg, row.att_err_deg < cfg["att_err_bound_deg"])
            for k, (te, lab, col) in enumerate([e for e in ev if e[0] <= st][-6:]):
                f.text(x0 + 0.20, 0.77 - k * 0.045, f"{hms(te)} {lab}", fontsize=12, family=MONO, color=col)
            m = d.t_s.values <= st
            axa = f.add_axes([x0 + 0.02, 0.28, 0.42, 0.16])
            axa.axhline(cfg["att_err_bound_deg"], color=RED, lw=1, ls="--")
            axa.text(Tend * 0.99, cfg["att_err_bound_deg"] + 6, "30° bound", color=RED, fontsize=11, ha="right")
            axa.plot(d.t_s.values[m], d.att_err_deg.values[m], color=AMBER, lw=1.8)
            axa.set_xlim(0, Tend); axa.set_ylim(0, 185); axa.set_ylabel("att err [deg]", fontsize=12)
            axa.tick_params(labelsize=10, labelbottom=False); axa.axvspan(0, cfg["att_grace_s"], color=GRID, alpha=0.5)
            axw = f.add_axes([x0 + 0.02, 0.09, 0.42, 0.17])
            for k, col in enumerate([CYAN, GREEN, AMBER, "#c08cff"]):
                axw.plot(d.t_s.values[m], d[f"rw{k}_rpm"].values[m], color=col, lw=1.4, label=f"RW{k}")
            axw.set_xlim(0, Tend); axw.set_ylim(-6500, 6500); axw.set_ylabel("wheel [rpm]", fontsize=12)
            axw.set_xlabel("sim time [s]", fontsize=12); axw.tick_params(labelsize=10)
            axw.legend(loc="lower left", ncol=4, fontsize=10, frameon=False, labelcolor=DIM)
            for te, lab, col in ev:
                if te <= st:
                    for axx in (axa, axw):
                        axx.axvline(te, color=col, lw=1.2, alpha=0.8)
        if t < T0 + 0.4:
            a = min(fade(t, T_OP), 1 - fade(t, T0 - 0.3))
            f.text(0.5, 0.50, "Same two faults · one change: isolation suppressed", fontsize=32, ha="center",
                   weight="bold", alpha=a, bbox=dict(fc=BG, ec=CYAN, lw=2, alpha=0.95 * a, pad=18))
        if t > T1 + 0.3:                                       # end card: safety metric FIRST, peak only in context
            a = fade(t, T1 + 0.3)
            card(f, 0.12, 0.16, 0.76, 0.62, CYAN, a, z=10)
            ft = lambda *aa, **kk: f.text(*aa, zorder=11, **kk)
            ft(0.5, 0.735, f"Safety rule: attitude error > {cfg['att_err_bound_deg']:.0f}° for at most "
                               f"{lim:.0f} s ({lim / 60:.0f} min) in one stretch", fontsize=21, ha="center",
                   weight="bold", alpha=a)
            hdr = ["", "full policy", "isolation suppressed"]
            rows = [("longest stretch > 30°", f"{R['full']['longest_att_err_gt_30deg_run_s']:,.0f} s",
                     f"{R['no_isolate']['longest_att_err_gt_30deg_run_s']:,.0f} s"),
                    ("verdict", "ATTITUDE LOSS" if R["full"]["violations"] else "passes",
                     "ATTITUDE LOSS" if R["no_isolate"]["violations"] else "passes"),
                    (f"{nsw} nearby variants failing", f"{sf}/{nsw}", f"{sn}/{nsw}")]
            xs = [0.17, 0.52, 0.72]
            for k, h_ in enumerate(hdr):
                ft(xs[k], 0.665, h_, fontsize=18, color=DIM, alpha=a, weight="bold")
            for r_, row in enumerate(rows):
                y = 0.605 - r_ * 0.065
                ft(xs[0], y, row[0], fontsize=20, alpha=a)
                ft(xs[1], y, row[1], fontsize=22, weight="bold", color=RED, alpha=a, family=MONO)
                ft(xs[2], y, row[2], fontsize=22, weight="bold", color=GREEN, alpha=a, family=MONO)
            if t > T1 + 3.2:
                b = fade(t, T1 + 3.2)
                pf, pn = R["full"]["peak_att_err_after_grace_deg"], R["no_isolate"]["peak_att_err_after_grace_deg"]
                ft(0.17, 0.375, f"Context: peak error {pf:.0f}° vs {pn:.0f}°. With isolation suppressed the craft "
                                    f"still swings to {pn:.0f}° briefly", fontsize=17, color=DIM, alpha=b)
                ft(0.17, 0.340, f"(time > 30°: {R['no_isolate']['time_att_err_gt_30deg_s']:.0f} s in total) "
                                    f"but recovers; the full policy stays tumbling ({R['full']['time_att_err_gt_30deg_s']:,.0f} s "
                                    f"total).", fontsize=17, color=DIM, alpha=b)
                ft(0.17, 0.265, "Cause: the policy spends its ONE isolation on the mild wheel (RW0),\nso the dead "
                                    "RW1 stays in the control loop.", fontsize=19, color=AMBER, alpha=b, weight="bold")
                ft(0.17, 0.195, "minimized case · the original run 173 also fails with the policy off",
                       fontsize=15, color=DIM, alpha=b, style="italic")
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s0 problem framing (3 beats, verbatim)
def s0(D, T):
    # Narration-only opening: slow Ken-Burns over the rendered s1 replay still (dimmed), short title, no transcript.
    img = np.asarray(Image.open(os.path.join(HERE, "v4_still_s1_mid.png")).convert("RGB"))
    h, w = img.shape[:2]
    s = mv.Seg("s0", {int(5.0 * FPS): STILL("s0_open")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf(); u = t / T
        z = 1.0 + 0.30 * u                                  # zoom in slowly toward the left spacecraft
        cx, cy = w * (0.5 - 0.30 * u), h * (0.5 - 0.10 * u)
        hw, hh = w / (2 * z), h / (2 * z)
        cx = min(max(cx, hw), w - hw); cy = min(max(cy, hh), h - hh)
        ax = f.add_axes([0, 0, 1, 1]); ax.axis("off")
        ax.imshow(img, interpolation="bilinear"); ax.set_xlim(cx - hw, cx + hw); ax.set_ylim(cy + hh, cy - hh)
        ax.add_patch(plt.Rectangle((0, 0), w, h, color=BG, alpha=0.55 * fade(t, 0.0, 1.5) + 0.25))
        a = fade(t, 0.3, 1.2) * (1 - fade(t, T - 0.8))
        f.text(0.5, 0.52, "FaultForge", fontsize=84, ha="center", va="center", weight="bold", color=FG, alpha=a)
        f.text(0.5, 0.40, "Basilisk spacecraft simulation  \u00b7  AI-guided fault search", fontsize=26,
               ha="center", va="center", color=AMBER, alpha=a)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s2 roles card
ROLES = [("1", "Scenario search", "proposes fault scenarios as JSON (informed or blind to the rules)", True),
         ("2", "Blind rule inference", "infers the policy's hidden rules from outcomes only", True),
         ("3", "Diagnosis", "explains a minimized counterexample", True),
         ("4", "Repair selection", "selects + parameterizes from an engineer-provided menu of repairs", True),
         ("", "Basilisk simulation", "every scenario is simulated; no model judges a result", False),
         ("", "Minimizer + policy-off re-run", "shrinks faults; checks the policy caused it", False),
         ("", "Gate", "strict (0 new violations) or budget (net > 0, ≤3 clean runs broken)", False)]


def s2(D, T):
    s = mv.Seg("s2", {int((T - 1) * FPS): STILL("s2_roles")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "How FaultForge found it", "Muse Spark has four labeled roles; everything that decides is plain code",
               "src/llm_search.py (informed + blind), src/repair.py, src/ff_sim.py, src/minimize.py, src/gated_v2.py")
        for k, (n, ttl, desc, muse) in enumerate(ROLES):
            a = fade(t, 0.6 + k * 0.6)
            y = 0.76 - k * 0.095 - (0.03 if not muse else 0)
            col = AMBER if muse else CYAN
            card(f, 0.08, y - 0.02, 0.84, 0.075, col, 0.95 * a)
            f.text(0.10, y + 0.012, ("MUSE  role " + n) if muse else "CODE", fontsize=17, weight="bold", color=col,
                   alpha=a, family=MONO)
            f.text(0.27, y + 0.012, ttl, fontsize=22, weight="bold", alpha=a)
            f.text(0.55, y + 0.012, desc, fontsize=15, color=DIM, alpha=a)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s3 LIVE take (ffmpeg composition, as v3)
def _txt(name, s):
    p = os.path.join(BUILD, f"txt_{name}.txt"); open(p, "w").write(s); return p


def _still(mp4, t, name):
    p = os.path.join(HERE, name)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", mp4, "-frames:v", "1", p], check=True)


def s3(D, T):
    ev = [json.loads(l) for l in open(vs.LIVE_CAST).read().splitlines()[1:]]
    w0 = next(t for t, _, d in ev if "chat/completions" in d or "json_mode" in d)
    w1 = next(t for t, _, d in ev if "HTTP 200" in d)
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
    nr = len(lj["runs"])
    main = _txt("main", f"Muse proposed {nr} tests → sim found {nv} failures")
    sub = _txt("sub", f"{nv} of {nr} Muse-proposed fault scenarios broke a safety rule in Basilisk (attitude loss)")
    prov = _txt("prov", "\n".join([
        f"LIVE META CALL   model {pv['model']} (requested {pv['model_requested']})   endpoint {pv['endpoint']}",
        f"response id {pv['response_id']}   {pv.get('request_id_header', 'x-request-id')} {pv['request_id']}",
        f"HTTP {pv['http_status']}   latency {pv['latency_s']:.1f} s   tokens {pv['usage']['total_tokens']} "
        f"(prompt {pv['usage']['prompt_tokens']}, completion {pv['usage']['completion_tokens']})   "
        f"record {os.path.relpath(vs.LIVE_JSON, ROOT)}",
        "only this live call has a request id; recorded calls do not"]))
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
          f"drawbox=x=110:y=170:w=1700:h=330:color={BG}@0.94:t=fill:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawbox=x=110:y=170:w=1700:h=330:color={CYAN}:t=3:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTB}:textfile={ff(main)}:x=(w-tw)/2:y=215:fontsize=64:fontcolor={FG}:"
          f"enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTB}:textfile={ff(sub)}:x=(w-tw)/2:y=315:fontsize=28:fontcolor={AMBER}:"
          f"enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTB}:text='real `make live` output, unedited':x=(w-tw)/2:y=375:fontsize=22:"
          f"fontcolor={DIM}:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawbox=x=0:y=930:w={W}:h=150:color={BG}@0.95:t=fill:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawbox=x=0:y=930:w={W}:h=2:color={CYAN}:t=fill:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTM}:textfile={ff(prov)}:x=40:y=945:fontsize=21:line_spacing=8:fontcolor={FG}:"
          f"enable='gte(t,{t_h + 0.4:.3f})',format=yuv420p[v]")
    out = os.path.join(BUILD, "s3.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", take, "-filter_complex", fc, "-map", "[v]",
                    "-t", f"{T:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "20", out],
                   check=True)
    _still(out, min(t_h + 1.5, T - 0.2), STILL("s3_live"))
    return int(round(T * FPS))


# ------------------------------------------------------------------ s4 defect classes
def s4(D, T):
    DF = vs.DF
    rows = [("D1", "Isolation lock-in", DF["d1"], "isolates a mild wheel first; a later dead wheel can't be isolated",
             "a6e8087b", "python3 src/defects.py --replay a6e8087b full"),
            ("D2", "Isolates a still-needed wheel", DF["d2"], "isolation leaves too few healthy wheels for control",
             "b8aa55fd", "python3 src/defects.py --replay b8aa55fd full"),
            ("D3", "Safe-mode induced", DF["d3"], "safe-mode entry/exit chatter drives the violation",
             "8a5158f3", "python3 src/defects.py --replay 8a5158f3 full"),
            ("D4", "Implementation bug in the policy", DF["tie"],
             "same-step threshold crossings resolved by wheel index, not residual", vs.TIE_KEY,
             f"python3 src/defects.py --tiebreak {vs.TIE_KEY}")]
    rp = _replay_cmds()
    s = mv.Seg("s4", {int((T - 1) * FPS): STILL("s4_defects")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, f"{DF['n']} policy-caused cases → 3 defect classes + 1 policy bug",
               "classified by ablation replays (isolation off / safe mode off); each has a one-command replay",
               "data/satfix/defects.json, data/satfix/defects.md · src/defects.py")
        for k, (tag, ttl, n, desc, key, _) in enumerate(rows):
            a = fade(t, 0.8 + k * (T - 6) / 4.5)
            y = 0.70 - k * 0.165; col = RED if tag == "D4" else AMBER
            card(f, 0.06, y - 0.045, 0.88, 0.14, col, 0.95 * a, lw=3 if tag == "D4" else 2)
            f.text(0.08, y + 0.035, tag, fontsize=30, weight="bold", color=col, alpha=a)
            f.text(0.15, y + 0.045, ttl, fontsize=24, weight="bold", alpha=a)
            f.text(0.15, y + 0.005, desc, fontsize=16, color=DIM, alpha=a)
            f.text(0.15, y - 0.033, "$ " + rp.get(tag, _), fontsize=13, family=MONO, color=CYAN, alpha=a)
            lab = f"{n}/{DF['n']}" if tag == "D4" else f"{n}"
            f.text(0.92, y + 0.025, lab, fontsize=34, weight="bold", ha="right", color=col, alpha=a, family=MONO)
            f.text(0.92, y - 0.012, "cases" + (" (overlaps D1-D3)" if tag == "D4" else ""), fontsize=13,
                   ha="right", color=DIM, alpha=a)
        s.frame()
    return s.close()


def _replay_cmds():
    """replay commands as written in README '## Defects found' (single source); falls back to the defaults."""
    out = {}
    try:
        txt = open(P("README.md")).read()
        sec = txt.split("## Defects found", 1)[1].split("\n## ", 1)[0]
        for line in sec.splitlines():
            if line.startswith("| D") and "`" in line:
                tag = line.split("|")[1].strip()[:2]
                cmds = [c for c in line.split("`")[1::2] if c.startswith(("python3", "make"))]
                if cmds:
                    out[tag] = cmds[0]
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ s5 chart 1: benchmarks, exactly 4 bars
def s5(D, T):
    A = vs.BF["matched"]["all"]                                   # data/matched/summary.json (includes cmp arms)
    v = lambda a: A[a]["violations_per_sim"]
    bars = [("random", "plain random\n(uniform)", GREY, ""),
            ("oneshot", "1 Muse call\n+ random mutations\n(no feedback)", ORANGE, ""),
            ("muse", "Muse closed loop\n(adaptive)", AMBER, ""),
            ("matchall", "marginals-matched random*\nsamples Muse's learned distribution\n(needs finished Muse runs)", GREEN, "//")]
    s = mv.Seg("s5", {int((T - 1) * FPS): STILL("s5_bench")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf(); g = float(np.clip((t - 0.8) / 3.0, 0, 1))
        header(f, "Chart 1 · Benchmarks: violations per simulation",
               "equal budgets, 3 seeds (means) · higher = finds more safety-rule failures per simulated scenario",
               "data/cmp/summary.json · data/matched/summary.json")
        ax = f.add_axes([0.10, 0.32, 0.80, 0.48])
        vals = [v(k) for k, *_ in bars]; ymax = max(vals) * 1.22
        for x, ((k, lab, col, ht), val) in enumerate(zip(bars, vals)):
            ax.bar([x], [val * g], color=col, width=0.58, hatch=ht, edgecolor=BG if ht else col)
            if g > 0.95:
                ax.text(x, val + ymax * 0.02, f"{val:.3f}", ha="center", fontsize=24, weight="bold", color=col)
        ax.set_xticks(range(len(bars))); ax.set_xticklabels([b[1] for b in bars], fontsize=16)
        for x, b in enumerate(bars):
            ax.get_xticklabels()[x].set_color(b[2])
        ax.set_ylim(0, ymax); ax.tick_params(labelsize=13); ax.set_ylabel("violations / sim", fontsize=15)
        a = fade(t, 4.0)
        f.text(0.10, 0.165, "* hindsight baseline: each parameter is drawn from the marginals of Muse's own finished "
                            "proposals, so it cannot run before Muse has", fontsize=15, color=GREEN, alpha=a)
        f.text(0.10, 0.130, f"Also run: CMA-ES {v('cmaes'):.3f} · random limited to Muse's fault families "
                            f"{v('matchfam'):.3f} · Muse rules-blind {v('museblind'):.3f}", fontsize=15, color=DIM,
               alpha=a)
        f.text(0.10, 0.095, "Blind > informed is a hypothesis, not a result: higher viol/sim on 3/3 seeds, more coarse "
                            "signatures on only 2/3", fontsize=15, color=DIM, alpha=a)
        b = fade(t, T - 6.5)
        f.text(0.5, 0.835, "Takeaway: Muse's closed loop discovers where failures live", fontsize=26, weight="bold",
               ha="center", color=AMBER, alpha=b,
               bbox=dict(fc=PANEL, ec=AMBER, lw=2, alpha=0.95 * b, pad=10))
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s6 repair: held-out first, then the gates
def s6(D, T):
    GF = vs.GF; acc = vs.ACC; g = acc["gate"] if acc else {}; FR = vs.FRESH
    rej_b = [x["name"] for x in GF["bud"] if x["decision"] != "accept"]
    wv = acc["waivers"] if acc else []
    wname = ", ".join(w.get("suite_id", w.get("run", "?")) if isinstance(w, dict) else str(w) for w in wv) or "-"
    nid = g.get("new_violation_ids", []); cb = set(g.get("clean_broken_ids", []))
    already = [x for x in nid if x not in cb]
    fx, nw, cl, net = (int(g.get(k, 0)) for k in ("fixes", "runs_with_new_violations", "clean_to_violating", "net_fixes"))
    assert fx - nw == net, (fx, nw, net)
    H = FR["v1"]["heldout_fixed"]["all"]["n"]
    s = mv.Seg("s6", {int((T - 1) * FPS): STILL("s6_gates")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Repair: Muse picks from a menu; a code gate decides",
               "Muse selects and parameterizes from an engineer-provided menu of repair options; "
               "every candidate is re-run on the full 3,508-run suite",
               "data/gated/*_gate.json · data/gated/waivers.md · data/gated/fresh/result_{v1,b1t1}.json")
        a = fade(t, 0.4)
        card(f, 0.05, 0.705, 0.90, 0.10, GREEN, 0.95 * a, lw=3)
        f.text(0.5, 0.765, f"Held-out: {FR['h_fixed']} fixed, {FR['h_new']} newly broken", fontsize=36,
               weight="bold", ha="center", va="center", color=GREEN, alpha=a)
        f.text(0.5, 0.722, f"same {H} scenarios run against v1 and the accepted patch (paired) · small sample",
               fontsize=16, ha="center", va="center", color=DIM, alpha=a)
        b = fade(t, 3.0)
        card(f, 0.05, 0.10, 0.30, 0.57, GREY, 0.95 * b)
        f.text(0.07, 0.62, "STRICT gate", fontsize=26, weight="bold", alpha=b)
        f.text(0.07, 0.585, "accept only if 0 new violations", fontsize=16, color=DIM, alpha=b)
        f.text(0.20, 0.42, f"{GF['n_sx_rej']}/{GF['n_sx']}", fontsize=64, weight="bold", ha="center", color=RED, alpha=b)
        f.text(0.20, 0.36, "proposals REJECTED", fontsize=20, ha="center", color=RED, alpha=b, weight="bold")
        f.text(0.07, 0.17, "every fix also broke at least\none previously clean run", fontsize=16, color=DIM, alpha=b)
        c = fade(t, 6.0)
        card(f, 0.38, 0.10, 0.57, 0.57, GREEN, 0.95 * c)
        f.text(0.40, 0.62, "BUDGET gate", fontsize=26, weight="bold", alpha=c)
        f.text(0.40, 0.585, "net fixes > 0 and ≤ 3 previously clean runs broken (each named)", fontsize=16, color=DIM,
               alpha=c)
        if acc:
            f.text(0.40, 0.535, f"ACCEPTED {acc['name']}  ·  " + " · ".join(f"{k} {v:g}" for k, v in
                                                                         (acc.get("change") or {}).items()),
                   fontsize=17, weight="bold", color=GREEN, alpha=c, family=MONO)
            rows = [("suite runs fixed", f"{fx}", GREEN),
                    (f"runs with a new violation ({len(already)} already failing, {cl} clean)", f"−{nw}", AMBER),
                    ("net", f"{fx} − {nw} = +{net}", GREEN),
                    ("previously clean runs broken", f"{cl}", AMBER)]
            for k, (l_, v_, c_) in enumerate(rows):
                yy = 0.47 - k * 0.06
                f.text(0.40, yy, l_, fontsize=18, alpha=c, weight="bold" if l_ == "net" else "normal")
                f.text(0.93, yy, v_, fontsize=21, weight="bold", ha="right", color=c_, alpha=c, family=MONO)
            f.text(0.40, 0.215, f"broken + waived: {wname}", fontsize=16, family=MONO, color=AMBER, alpha=c)
        if rej_b:
            f.text(0.40, 0.165, f"later rounds ({', '.join(rej_b)}) REJECTED: only one budget patch accepted",
                   fontsize=15, color=RED, alpha=c)
        f.text(0.40, 0.125, "the budget gate admits named regressions by design", fontsize=14, color=DIM, alpha=c,
               style="italic")
        s.frame()
    return s.close()


def wrap(s, n):
    return textwrap.fill(s, n)


# ------------------------------------------------------------------ s7 limits + related work + close
def s7(D, T):
    lim = ["One simulated 6U-like CubeSat (Basilisk) and a fault-protection policy we wrote ourselves",
           "A random sampler matched to Muse's own proposals ties Muse once the failure region is known",
           "The single-fault grid (568/576 pass) is the policy's own acceptance test; thresholds and rules are ours"]
    s = mv.Seg("s7", {int((T - 1) * FPS): STILL("s7_limits")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Limits, and prior work", None, "README.md (Limits, Related work)")
        for k, l_ in enumerate(lim):
            a = fade(t, 0.4 + 0.5 * k)
            f.text(0.06, 0.80 - k * 0.08, "•  " + l_, fontsize=22, alpha=a)
        f.text(0.06, 0.80 - 3 * 0.08, "More in README (Limits): momentum dumping, menu-based repair, waivers, "
                                      "request ids, blind vs informed", fontsize=17, color=DIM, alpha=fade(t, 2.2),
               style="italic")
        a = fade(t, 3.5)
        card(f, 0.06, 0.25, 0.88, 0.16, CYAN, 0.95 * a)
        f.text(0.08, 0.36, "Builds on LLM-Falsifier (ArjomandBigdeli, Zhou, Bak, arXiv:2609.20752) and simulation-based "
                           "falsification (S-TaLiRo / Ψ-TaLiRo, Breach).", fontsize=17, alpha=a)
        f.text(0.08, 0.30, "We implemented the LLM-guided falsification + minimization + gated-repair loop for "
                           "spacecraft fault protection.", fontsize=17, alpha=a)
        b = fade(t, T - 6)
        f.text(0.5, 0.15, f"git clone https://{v2.REPO_URL} && cd meta-hack && make replay", fontsize=24,
               family=MONO, ha="center", color=CYAN, alpha=b, weight="bold")
        s.frame()
    return s.close()


SEGS = dict(s0=s0, s1=s1, s2=s2, s3=s3, s4=s4, s5=s5, s6=s6, s7=s7)
assert list(SEGS) == [s["id"] for s in vs.SEGMENTS]


def _run(k):
    T = seg_durs()[k]
    return k, SEGS[k]({}, T)


def mux(durs):
    ids = list(SEGS); vids = [os.path.join(BUILD, f"{k}.mp4") for k in ids]
    inputs, parts = [], []
    for n, (k, v) in enumerate(zip(ids, vids)):
        inputs += ["-i", v]
        parts.append(f"[{n}:v]fps={FPS},scale={W}:{H},setsar=1,format=yuv420p,trim=0:{durs[k]:.3f},"
                     f"setpts=PTS-STARTPTS[v{n}]")
    m = len(ids)
    for n, k in enumerate(ids):
        wav = os.path.join(HERE, "vo_v4", f"{k}.wav"); T = durs[k]
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
    args = [a for a in sys.argv[1:] if a in SEGS]
    only = args or list(SEGS)
    if "--mux-only" not in sys.argv:
        only = sorted(only, key=lambda k: -durs[k])
        with Pool(min(len(only), int(os.environ.get("FF_RENDER_WORKERS", "2")))) as p:
            for name, n in p.imap_unordered(_run, only):
                print(name, n, "frames", round(n / FPS, 1), "s", flush=True)
    if all(os.path.exists(os.path.join(BUILD, f"{k}.mp4")) for k in SEGS):
        mux(durs)
    else:
        print("not all segments rendered yet; skipping mux")
