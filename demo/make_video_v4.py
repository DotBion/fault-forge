"""Render FaultForge demo video v4 from repo data + demo/vo_v4 narration + the real live take.

    bash demo/render_v4.sh                 # the one command: VO (cached) -> segments -> mux -> mp4
    python3 demo/make_video_v4.py [s1 s6]  # (re)render only some segments, then re-mux

Segment ids, lengths and narration live in demo/v4_script.py (lengths: demo/vo_v4/durations.json).
  s1  minimized case a6e8087b: Basilisk split replay, full v1 policy vs the SAME policy with only isolation suppressed
      (demo/data/hl4_*.csv from demo/replay_causal_v4.py); end card leads with the safety-rule metric
      (data/satfix/causal_replay.json, causal_sweep.json), the 137 deg peak only shown with that context.
  s3  real asciinema take demo/live/take1.cast; only the Muse wait is sped up, with a burned-in label.
  s4  defect classes from data/satfix/defects.json (+ tie-break count via src/defects.py).
  s5  chart 1: benchmarks (data/cmp/summary.json) + a marked matched-random slot (data/matched/summary.json if present).
  s6  gates from data/gated/*_gate.json; chart 2 = plots/gated_repair_trend.png (`gated_v2.py report`).
Only two charts: s5 and s6. v3 files are untouched; this writes demo/build_v4/ (not committed) and the mp4.
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
    T0, T1 = 2.0, T - 9.5
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
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
            a = 1 - fade(t, T0 - 0.3)
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
    prov = _txt("prov", "\n".join([
        f"model            {pv['model']}   (requested {pv['model_requested']})",
        f"endpoint         {pv['endpoint']}",
        f"response id      {pv['response_id']}",
        f"{pv.get('request_id_header', 'x-request-id'):<17}{pv['request_id']}",
        f"HTTP {pv['http_status']}  latency {pv['latency_s']:.1f} s  tokens {pv['usage']['total_tokens']}",
        f"result           {nv}/{len(lj['runs'])} scenarios violated a safety constraint",
        f"record           {os.path.relpath(vs.LIVE_JSON, ROOT)}",
        "note             only this live call has a request id; recorded calls do not"]))
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
          f"drawbox=x=230:y=150:w=1460:h=370:color={BG}@0.93:t=fill:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawbox=x=230:y=150:w=1460:h=370:color={CYAN}:t=3:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTB}:text='Provenance of this live call (from the JSON record it wrote)':"
          f"x=270:y=175:fontsize=26:fontcolor={CYAN}:enable='gte(t,{t_h + 0.4:.3f})',"
          f"drawtext=fontfile={FONTM}:textfile={ff(prov)}:x=270:y=225:fontsize=24:line_spacing=10:fontcolor={FG}:"
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


# ------------------------------------------------------------------ s5 chart 1: benchmarks + matched slot
def s5(D, T):
    S = json.load(open(P("data", "cmp", "summary.json")))["arms"]
    arms = ["muse", "museblind", "cmaes", "random"]
    lab = {"muse": "Muse\n(informed)", "museblind": "Muse\n(blind)", "cmaes": "CMA-ES", "random": "random\n(uniform)"}
    vps = {a: S[a]["mean"]["violations_per_sim"] for a in arms}
    sig = {a: S[a]["mean"]["unique_patterns_coarse"] for a in arms}
    M = vs.BF["matched"]
    s = mv.Seg("s5", {int((T - 1) * FPS): STILL("s5_bench")}); f = s.fig
    cols = {"muse": AMBER, "museblind": ORANGE, "cmaes": CYAN, "random": GREY, "matched": GREEN}
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf(); g = float(np.clip((t - 0.8) / 3.0, 0, 1))
        header(f, "Chart 1 · Benchmarks: equal budgets, 3 seeds (means)",
               f"Muse {vps['muse']:.3f} vs random {vps['random']:.3f} violations/sim (≈{vs.RATIO:.0f}×) · distinct "
               f"fault-combination signatures (coarse) {sig['muse']:.1f} vs CMA-ES {sig['cmaes']:.1f}",
               "data/cmp/summary.json" + (" · " + M["src"] if M else " · matched random: data/matched/summary.json "
                                                                    "(not present at render time)"))
        MA = (M or {}).get("arms") or {}
        mk = [k for k in ("matchfam", "matchall", "oneshot") if k in MA]
        mlab = {"matchfam": "MATCHED\nfamilies", "matchall": "MATCHED\nfam+param", "oneshot": "1 Muse\ncall+\nmutate"}
        mcol = {"matchfam": GREEN, "matchall": GREEN, "oneshot": ORANGE}
        for p, (vals, ttl, fmt) in enumerate([(vps, "violations per simulation", "{:.3f}"),
                                              (sig, "distinct fault-combination signatures (coarse)", "{:.1f}")]):
            ax = f.add_axes([0.06 + p * 0.49, 0.25 if MA else 0.20, 0.42, 0.53 if MA else 0.58])
            hs = [vals[a] * g for a in arms]
            mvals = [MA[k]["vps" if p == 0 else "sig"] for k in mk]
            ax.bar(range(len(arms)), hs, color=[cols[a] for a in arms], width=0.62)
            ymax = max(list(vals.values()) + [v for v in mvals if v is not None]) * 1.25
            if mk:
                for j, (k, v) in enumerate(zip(mk, mvals)):
                    x = len(arms) + j
                    ax.bar([x], [(v or 0) * g], color=mcol[k], width=0.62, hatch="//", edgecolor=BG)
                    ax.text(x, (v or 0) * g + ymax * 0.02, fmt.format(v) if (g > 0.95 and v is not None) else "",
                            ha="center", fontsize=15, color=mcol[k])
                xl = [lab[a] for a in arms] + [mlab[k] for k in mk]
            else:
                ax.bar([len(arms)], [ymax * 0.9], color="none", width=0.62, edgecolor=GREEN, ls="--", lw=2)
                ax.text(len(arms), ymax * 0.45, "PENDING\nnot run\nin time" if p == 0 else "PENDING", ha="center",
                        va="center", fontsize=14, color=GREEN, weight="bold")
                xl = [lab[a] for a in arms] + ["MATCHED\nrandom"]
            for k, a in enumerate(arms):
                ax.text(k, hs[k] + ymax * 0.02, fmt.format(vals[a]) if g > 0.95 else "", ha="center", fontsize=15)
            ax.set_xticks(range(len(xl))); ax.set_xticklabels(xl, fontsize=10 if mk else 13)
            for j, k in enumerate(mk or ["matchfam"]):
                ax.get_xticklabels()[len(arms) + j].set_color(mcol.get(k, GREEN))
            ax.set_ylim(0, ymax); ax.set_title(ttl, fontsize=18, color=FG, pad=12); ax.tick_params(labelsize=12)
        a = fade(t, 4.5)
        notes = ["Signatures are fault-type combinations, not defects (the 276 cases reduce to D1-D4). "
                 "MATCHED = random restricted to Muse's fault families."]
        if MA:
            notes.append("MATCHED fam+param also samples each parameter from Muse's own proposals (a hindsight "
                         "baseline). 1 Muse call+mutate: one 40-scenario bank, then random mutations.")
        notes.append("Hypothesis, not a result: blind Muse beats informed on viol/sim on 3/3 seeds but on "
                     "coarse signatures on only 2/3.")
        for j, n in enumerate(notes):
            f.text(0.07, 0.055 + 0.03 * (len(notes) - 1 - j), n, fontsize=13 if MA else 14, color=DIM, alpha=a)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s6 gates + chart 2 trend
def s6(D, T):
    GF = vs.GF; acc = vs.ACC; g = acc["gate"] if acc else {}
    rej_b = [x["name"] for x in GF["bud"] if x["decision"] != "accept"]
    wv = acc["waivers"] if acc else []
    wname = ", ".join(w.get("suite_id", w.get("run", "?")) if isinstance(w, dict) else str(w) for w in wv) or "-"
    trend = P("plots", "gated_repair_trend.png")
    img = np.asarray(Image.open(trend).convert("RGB")) if os.path.exists(trend) else None
    FR = vs.FRESH
    t_sw = T * 0.42
    s = mv.Seg("s6", {int(t_sw * FPS) - 5: STILL("s6_gates"), int((T - 1) * FPS): STILL("s6_trend")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        if t < t_sw:
            header(f, "Repair: Muse picks from a menu; a code gate decides",
                   "Muse selects and parameterizes from an engineer-provided menu of repair options; "
                   "every candidate is re-run on the full suite",
                   "data/gated/*_gate.json · data/gated/rejects_table.md · data/gated/waivers.md")
            a = fade(t, 0.5)
            card(f, 0.05, 0.16, 0.42, 0.66, GREY, 0.95 * a)
            f.text(0.07, 0.76, "STRICT gate", fontsize=28, weight="bold", alpha=a)
            f.text(0.07, 0.715, "accept only if 0 new violations", fontsize=17, color=DIM, alpha=a)
            f.text(0.26, 0.52, f"{GF['n_sx_rej']}/{GF['n_sx']}", fontsize=72, weight="bold", ha="center", color=RED,
                   alpha=a)
            f.text(0.26, 0.45, "proposals REJECTED", fontsize=22, ha="center", color=RED, alpha=a, weight="bold")
            f.text(0.07, 0.24, "every fix also broke at least one\npreviously clean run", fontsize=16, color=DIM,
                   alpha=a)
            b = fade(t, 2.5)
            card(f, 0.53, 0.16, 0.42, 0.66, GREEN, 0.95 * b)
            f.text(0.55, 0.76, "BUDGET gate", fontsize=28, weight="bold", alpha=b)
            f.text(0.55, 0.715, "net fixes > 0 and ≤ 3 clean runs broken (each named)", fontsize=16, color=DIM, alpha=b)
            if acc:
                f.text(0.55, 0.64, f"ACCEPTED  {acc['name']}", fontsize=24, weight="bold", color=GREEN, alpha=b)
                f.text(0.55, 0.60, " · ".join(f"{k} {v:g}" for k, v in (acc.get("change") or {}).items()), fontsize=14,
                       family=MONO, color=DIM, alpha=b)
                for k, (l_, v_, c_) in enumerate([("fixes", f"{int(g.get('fixes', 0))}", GREEN),
                                                  ("net", f"+{int(g.get('net_fixes', 0))}", GREEN),
                                                  ("clean runs broken", f"{int(g.get('clean_to_violating', 0))}", AMBER)]):
                    f.text(0.55, 0.52 - k * 0.055, l_, fontsize=19, alpha=b)
                    f.text(0.90, 0.52 - k * 0.055, v_, fontsize=22, weight="bold", ha="right", color=c_, alpha=b,
                           family=MONO)
                f.text(0.55, 0.325, f"broken + waived: {wname}", fontsize=15, family=MONO, color=AMBER, alpha=b)
            if rej_b:
                f.text(0.55, 0.265, f"next round ({', '.join(rej_b)}) REJECTED:", fontsize=15, color=RED, alpha=b)
                f.text(0.55, 0.235, "only one budget round accepted", fontsize=15, color=RED, alpha=b)
            f.text(0.55, 0.185, "the budget gate admits regressions by design", fontsize=14, color=DIM, alpha=b,
                   style="italic")
        else:
            header(f, "Chart 2 · Does the accepted patch cut fresh violations?",
                   "fresh Muse search + uniform random + fixed held-out set, run against v1 and against b1t1",
                   "plots/gated_repair_trend.png · data/gated/fresh/result_{v1,b1t1}.json · data/gated/summary_v2.json")
            a = fade(t, t_sw)
            if img is not None:
                ax = f.add_axes([0.02, 0.12, 0.60, 0.76]); ax.imshow(img); ax.axis("off")
            else:
                v2.placeholder(f, 0.04, 0.17, 0.56, 0.68, "chart 2 pending", "plots/gated_repair_trend.png", a)
            card(f, 0.63, 0.17, 0.33, 0.68, CYAN, 0.95 * a)
            if FR:
                A, B = FR["v1"], FR["b1t1"]
                rows = [("fresh Muse search", A["muse"], B["muse"]), ("uniform random", A["random"], B["random"]),
                        ("held-out (fixed, paired)", A["heldout_fixed"]["all"], B["heldout_fixed"]["all"])]
                f.text(0.65, 0.80, "violating runs", fontsize=20, weight="bold", alpha=a)
                f.text(0.81, 0.765, "v1", fontsize=16, color=DIM, alpha=a, ha="right")
                f.text(0.94, 0.765, "b1t1", fontsize=16, color=DIM, alpha=a, ha="right")
                for k, (l_, x, y) in enumerate(rows):
                    yy = 0.70 - k * 0.075
                    f.text(0.65, yy, l_, fontsize=16, alpha=a)
                    f.text(0.81, yy - 0.032, f"{x['violating']}/{x['n']}", fontsize=18, family=MONO, ha="right", alpha=a)
                    c_ = GREEN if y["rate"] < x["rate"] else RED if y["rate"] > x["rate"] else FG
                    f.text(0.94, yy - 0.032, f"{y['violating']}/{y['n']}", fontsize=18, family=MONO, ha="right",
                           color=c_, alpha=a, weight="bold")
                verdict = ("modest cut" if FR["cut_muse"] and FR["cut_heldout"] else
                           "mixed evidence" if FR["cut_muse"] or FR["cut_heldout"] else "no cut")
                f.text(0.65, 0.44, f"Verdict: {verdict}", fontsize=21, weight="bold",
                       color=GREEN if verdict == "modest cut" else AMBER, alpha=a)
                if FR.get("h_fixed") is not None:
                    f.text(0.65, 0.395, f"paired held-out: {FR['h_fixed']} fixed, {FR['h_new']} new", fontsize=16,
                           color=FG, alpha=a)
                f.text(0.65, 0.25, wrap("Muse/random arms use new seeds per policy (unpaired: Muse seed "
                                        f"{A['muse_seed']} vs {B['muse_seed']}); held-out is the same 300 scenarios "
                                        "for both (paired). Small samples.", 44), fontsize=13, color=DIM, alpha=a)
            else:
                f.text(0.65, 0.70, "fresh-search check:\nPENDING", fontsize=24, weight="bold", color=AMBER, alpha=a)
        s.frame()
    return s.close()


def wrap(s, n):
    return textwrap.fill(s, n)


# ------------------------------------------------------------------ s7 limits + related work + close
def s7(D, T):
    lim = ["One simulated 6U-like CubeSat (Basilisk), 4 reaction wheels, static Sun direction, no momentum dumping",
           "Thresholds and safety rules are ours; the policy's 568/576 single-fault pass is its own acceptance test "
           "(thresholds tuned to it)",
           "Blind vs informed search: a hypothesis (higher viol/sim on 3/3 seeds, more signatures on only 2/3)",
           "Repairs come from an engineer-provided menu; the budget gate admits named regressions",
           "Recorded Muse calls carry no request ids; only the live take does"]
    s = mv.Seg("s7", {int((T - 1) * FPS): STILL("s7_limits")}); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Limits, and prior work", None, "README.md (Limits, Related work)")
        for k, l_ in enumerate(lim):
            a = fade(t, 0.4 + 0.5 * k)
            f.text(0.06, 0.82 - k * 0.07, "•  " + l_, fontsize=19, alpha=a)
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


SEGS = dict(s1=s1, s2=s2, s3=s3, s4=s4, s5=s5, s6=s6, s7=s7)
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
