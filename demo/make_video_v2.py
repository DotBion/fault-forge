"""Render FaultForge demo video v2 (draft) from repo data + demo/vo narration.

    bash demo/render_v2.sh                 # the one command: VO (cached) -> segments -> mux -> mp4
    python3 demo/make_video_v2.py [s4 s6]  # (re)render only some segments, then re-mux

Segment lengths come from demo/vo/durations.json (max(nominal, narration + pad); see demo/v2_script.py).
Repair beat auto-picks up data/gated/rejects_table.md, plots/gated_repair_trend.png and data/gated/waivers.md
when they exist, otherwise shows clearly marked PLACEHOLDER cards. Search numbers are read from
data/cmp/summary.json when it has 3 Muse-blind seeds, else data/cmp/blind_3seed_prelim.json.
Output: demo/faultforge_demo_v2_draft.mp4
"""
import json, os, re, subprocess, sys, textwrap
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_video as mv  # noqa: E402  (shared drawing helpers, colors, Seg writer)
import v2_script  # noqa: E402
from make_video import (plt, FPS, W, H, BG, PANEL, GRID, FG, DIM, CYAN, AMBER, ORANGE, GREY, RED, GREEN, ARM,  # noqa
                        MONO, fade, header, draw_sc, events, hms, matplotlib)
from PIL import Image  # noqa: E402

mv.BUILD = BUILD = os.path.join(HERE, "build_v2"); os.makedirs(BUILD, exist_ok=True)
OUT = os.path.join(HERE, "faultforge_demo_v2_draft.mp4")
REPO_URL = "github.com/DotBion/meta-hack"
HL_KEY = "a6e8087b7a52c977"
P = lambda *a: os.path.join(ROOT, *a)


def jl(p):
    with open(P(p)) as fh:
        return [json.loads(l) for l in fh]


def seg_durs():
    dj = os.path.join(HERE, "vo", "durations.json")
    d = json.load(open(dj)) if os.path.exists(dj) else {}
    return {s["id"]: float(d.get(s["id"], {}).get("seg_s", s["nominal"])) for s in v2_script.SEGMENTS}


# ------------------------------------------------------------------ data
def load_data():
    D = {}
    D["grid"] = [bool(r["violated"]) for r in jl("data/grid.jsonl")]
    S = json.load(open(P("data/cmp/summary.json")))
    nb = len(S["arms"].get("museblind", {}).get("per_seed", {}))
    if nb >= 3:
        D["src3"] = "data/cmp/summary.json"
        D["vps"] = {a: S["arms"][a]["mean"]["violations_per_sim"] for a in ARM}
        D["first"] = {a: S["arms"][a]["mean"]["sims_to_first_violation"] for a in ARM}
        D["by_seed"] = {a: [S["arms"][a]["per_seed"][k]["violations_per_sim"] for k in ("0", "1", "2")]
                        for a in ("muse", "museblind")}
    else:
        B = json.load(open(P("data/cmp/blind_3seed_prelim.json")))["arms"]
        D["src3"] = "data/cmp/blind_3seed_prelim.json"
        # prelim file covers muse/museblind/cmaes; arms it lacks (random) come from summary.json
        D["vps"] = {a: B[a]["viol_per_sim_mean"] if a in B else S["arms"][a]["mean"]["violations_per_sim"]
                    for a in ARM}
        D["first"] = {a: float(np.mean(B[a]["first_violation_sim_by_seed"])) if a in B
                      else S["arms"][a]["mean"]["sims_to_first_violation"] for a in ARM}
        D["by_seed"] = {a: B[a]["viol_per_sim_by_seed"] for a in ("muse", "museblind")}
    D["race"] = {}
    for a in ARM:
        rs = sorted(jl(f"data/cmp/{a}_seed1.jsonl"), key=lambda r: r["id"])[:300]
        D["race"][a] = np.cumsum([bool(r["violated"]) for r in rs])
    D["hl"] = json.load(open(os.path.join(HERE, "data", "hl2_runs.json")))
    assert D["hl"]["key"] == HL_KEY
    D["tel"] = {t: pd.read_csv(os.path.join(HERE, "data", f"hl2_{t}.csv")) for t in ("v1", "v1_nopolicy")}
    D["hl_src"] = None
    for p, v in S["patterns"].items():
        for a, l in v.items():
            for x in l:
                if x["key"] == HL_KEY:
                    D["hl_src"] = (a, x["seed"], x["id"])
    D["cfg"] = mv.ff_sim.CFG; D["pol"] = mv.ff_sim.POLICY
    calls = open(P("data/cmp/museblind_seed1_calls.jsonl")).read().splitlines()
    D["quote"] = json.loads(calls[4])["analysis"]          # line 5, round 4
    D["quote_round"] = json.loads(calls[4]).get("round")
    return D


# ------------------------------------------------------------------ s1 title
def s1(D, T):
    s = mv.Seg("s1"); f = s.fig
    rng = np.random.default_rng(3); sx, sy, ss = rng.random(260), rng.random(260), rng.random(260) ** 3 * 14
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf(); ax = f.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.scatter(sx, (sy + 0.004 * t) % 1, s=ss, c="#9fb3c8", alpha=0.35, lw=0)
        a1, a2, a3, a4 = fade(t, 0.2), fade(t, 1.2), fade(t, 4.8), fade(t, 8.0)
        ax.text(0.5, 0.66, "FaultForge", ha="center", fontsize=96, weight="bold", color=CYAN, alpha=a1)
        ax.text(0.5, 0.565, "Muse Spark hunts the failures a spacecraft's own safety logic causes", ha="center",
                fontsize=36, alpha=a1)
        ax.text(0.10, 0.42, "Existed before:", fontsize=26, color=DIM, weight="bold", alpha=a2)
        ax.text(0.30, 0.42, "Basilisk spacecraft simulator (open source) · Meta Muse Spark API", fontsize=26,
                color=DIM, alpha=a2)
        ax.text(0.10, 0.34, "Built this week:", fontsize=26, color=AMBER, weight="bold", alpha=a3)
        ax.text(0.30, 0.34, textwrap.fill("fault harness · FDIR / safe-mode policy · Muse-guided search · "
                                          "minimizer · policy on/off causal check · gated repair loop", 62),
                fontsize=26, color=FG, alpha=a3, va="top", linespacing=1.4)
        ax.text(0.5, 0.10, "CBxMeta AI-Hack · Push the Frontier · every number on screen is read from the repo",
                ha="center", fontsize=17, color=DIM, alpha=a4)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s2 credibility
def s2(D, T):
    s = mv.Seg("s2"); f = s.fig; pol = D["pol"]; cfg = D["cfg"]
    g = np.array(D["grid"]); n = len(g); side = int(np.ceil(np.sqrt(n))); nfail = int(g.sum())
    tfill = 0.45 * T
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "First: is the policy a strawman?",
               "4 reaction wheels (BCT RWp015, 4 mNm) · rule-based FDIR + safe mode · Basilisk 2.12.1",
               "data/grid.jsonl · src/ff_sim.py POLICY · docs/fdir_refs.md")
        k = int(n * np.clip((t - 0.3) / tfill, 0, 1))
        img = np.zeros((side, side, 4)); img[..., :3] = matplotlib.colors.to_rgb(GRID); img[..., 3] = 1
        for j in range(k):
            img[j // side, j % side, :3] = matplotlib.colors.to_rgb(RED if g[j] else GREEN)
        ax = f.add_axes([0.05, 0.12, 0.38, 0.71]); ax.imshow(img, interpolation="nearest"); ax.set_axis_off()
        f.text(0.05, 0.085, f"single-fault grid + nominal: {k:3d} / {n}   fail {int(g[:k].sum())}", fontsize=17,
               family=MONO, color=DIM)
        a = fade(t, 0.8)
        rules = [f"wheel torque residual > {pol['fdir_abs_Nm']:.0e} Nm for {pol['fdir_persist']} checks -> isolate",
                 f"at most ONE isolation (keep >= {pol.get('min_avail', 3)} wheels for 3-axis control)",
                 f"attitude error > {pol['att_safe_deg']:.0f}° for {pol['att_safe_dur_s']:.0f} s -> sun-safe mode",
                 f"failure = error > {cfg['att_err_bound_deg']:.0f}° for > {cfg['att_err_max_dur_s'] / 60:.0f} min, "
                 "battery floor, wheel saturation"]
        f.text(0.48, 0.80, "The policy under test", fontsize=22, color=DIM, alpha=a)
        for r, txt in enumerate(rules):
            f.text(0.48, 0.75 - r * 0.045, "· " + txt, fontsize=17, family=MONO, alpha=a)
        a = fade(t, tfill + 0.6)
        f.text(0.48, 0.44, f"{n - nfail} / {n}", fontsize=100, weight="bold", color=GREEN, alpha=a)
        f.text(0.48, 0.385, "single-fault and nominal runs pass. Looks safe.", fontsize=26, alpha=a)
        a = fade(t, tfill + 2.5)
        f.text(0.48, 0.25, textwrap.fill("Structure follows published CubeSat FDIR: EUCASS 2019 model-based FDIR "
                                         "(torque residual, isolate one of four wheels) · NASA SWEHB 9.07 · "
                                         "ECSS-E-ST-60-30C. Thresholds are ours.", 70),
               fontsize=17, color=DIM, alpha=a, va="top", linespacing=1.45)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s3 race + 3-seed chart
def s3(D, T):
    s = mv.Seg("s3", {int(0.85 * T * FPS): "v2_still_search.png"}); f = s.fig
    race = D["race"]; N = max(len(v) for v in race.values()); TR = 0.52 * T
    arms_img = np.asarray(Image.open(P("plots/arms_comparison.png")).convert("RGB"))
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        if t < TR + 0.8:
            header(f, "Search race: who finds failures faster?",
                   "Seed 1 · 300 simulations per arm · same fault space, same budget",
                   "data/cmp/{muse,museblind,cmaes,random}_seed1.jsonl")
            x = N * min(1, t / TR); m = int(np.floor(x))
            ax = f.add_axes([0.06, 0.12, 0.60, 0.72]); ax.grid(color=GRID, lw=0.8)
            for a, (lab, c) in ARM.items():
                y = race[a]
                ax.plot(np.arange(1, m + 1), y[:m], color=c, lw=3.2 if a == "muse" else 2.4,
                        ls="--" if a == "museblind" else "-")
                if m:
                    ax.plot([m], [y[m - 1]], "o", color=c, ms=9)
            ax.set_xlim(0, N); ax.set_ylim(0, max(v[-1] for v in race.values()) * 1.08)
            ax.set_xlabel("simulations run", fontsize=16); ax.set_ylabel("cumulative safety violations", fontsize=16)
            ax.tick_params(labelsize=13)
            f.text(0.70, 0.80, f"sims: {m:3d} / {N}", fontsize=26, family=MONO)
            for j, (a, (lab, c)) in enumerate(ARM.items()):
                v = int(race[a][m - 1]) if m else 0
                f.text(0.70, 0.70 - j * 0.10, lab, fontsize=26, color=c, weight="bold")
                f.text(0.92, 0.70 - j * 0.10, f"{v:3d}", fontsize=30, color=c, family=MONO, ha="right", weight="bold")
            f.text(0.70, 0.27, textwrap.fill("Muse: Muse Spark reads every result and proposes the next fault "
                                             "scenarios (policy rules visible). Muse-blind: rules hidden. CMA-ES: "
                                             "evolutionary optimizer on a safety-margin objective. random: uniform.",
                                             46), fontsize=14, color=DIM, va="top", linespacing=1.45)
        else:
            a0 = fade(t, TR + 0.8)
            header(f, "Three seeds: Muse finds failures fast, and finds many", "Equal budget per seed",
                   f"plots/arms_comparison.png · {D['src3']}", a=a0)
            axi = f.add_axes([0.03, 0.40, 0.94, 0.45]); axi.imshow(arms_img, alpha=a0); axi.set_axis_off()
            arms = list(ARM)
            f.text(0.06, 0.32, "violations / sim", fontsize=20, color=DIM, alpha=a0)
            f.text(0.06, 0.20, "first violation after", fontsize=20, color=DIM, alpha=a0)
            for k, a in enumerate(arms):
                b = fade(t, TR + 1.2 + 0.5 * k); x = 0.30 + k * 0.17
                f.text(x, 0.37, ARM[a][0], fontsize=22, color=ARM[a][1], weight="bold", alpha=b)
                f.text(x, 0.30, f"{D['vps'][a]:.3f}", fontsize=34, family=MONO, color=ARM[a][1], weight="bold", alpha=b)
                f.text(x, 0.18, f"~{D['first'][a]:.0f} sims", fontsize=30, family=MONO, color=ARM[a][1], alpha=b)
            f.text(0.06, 0.09, "mean over seeds 0-2 · a violation = any safety constraint breached in a 2-orbit run",
                   fontsize=15, color=DIM, alpha=a0)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s4 headline replay
def s4(D, T):
    s = mv.Seg("s4", {int(0.93 * T * FPS): "v2_still_headline.png"}); f = s.fig
    cfg = D["cfg"]; hl = D["hl"]; mn = hl["minimized_record"]; src = D["hl_src"]
    runs = [("v1", "SAFE-MODE POLICY ON"), ("v1_nopolicy", "POLICY OFF (same faults)")]
    tel = D["tel"]; Tend = float(tel["v1"].t_s.max())
    T0, T1 = 2.5, T - 6.0
    who = f"{ARM[src[0]][0]} (seed {src[1]}, run {src[2]})" if src else "Muse (muse_seed1_173)"
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, f"Found by Muse: counterexample {hl['key'][:8]}",
               f"{who} · minimized to {mn['n_faults_after']} faults in {mn['minimization_sims']} sims · "
               f"Basilisk replay, same faults, policy on vs off",
               "demo/data/hl2_{v1,v1_nopolicy}.csv · demo/replay_headline_v2.py · data/cmp/minimized.jsonl")
        st = Tend * np.clip((t - T0) / (T1 - T0), 0, 1)
        f.text(0.96, 0.935, hms(st), fontsize=34, family=MONO, ha="right", color=CYAN)
        f.text(0.96, 0.898, f"sim time  ×{Tend / (T1 - T0):.0f}", fontsize=15, family=MONO, ha="right", color=DIM)
        for c, (tag, ttl) in enumerate(runs):
            d = tel[tag]; run = hl[tag]; ev = events(run, cfg)
            j = max(int(np.searchsorted(d.t_s.values, st, side="right")) - 1, 0)
            row = d.iloc[j]; x0 = 0.04 + c * 0.48
            ok = not [e for e in ev if e[2] == RED and e[0] <= st]
            f.text(x0, 0.835, ttl, fontsize=22, weight="bold", color=FG)
            iso = [k for k in range(4) if row[f"rw{k}_avail"] == 0]
            f.text(x0, 0.805, f"mode {'SAFE' if row.safe_mode else 'NOMINAL':<8s} isolated "
                              f"{('RW' + ','.join(map(str, iso))) if iso else '-':<6s} att err {row.att_err_deg:5.1f}°",
                   fontsize=15, family=MONO, color=ORANGE if row.safe_mode else DIM)
            ax3 = f.add_axes([x0 - 0.01, 0.47, 0.22, 0.33], projection="3d"); ax3.set_facecolor(BG)
            sg = [row.sBR1, row.sBR2, row.sBR3]
            draw_sc(ax3, [0, 0, 0] if np.any(np.isnan(sg)) else sg, row.att_err_deg < cfg["att_err_bound_deg"])
            f.text(x0 + 0.005, 0.475, "spacecraft vs commanded attitude (dotted = commanded boresight)", fontsize=12,
                   color=DIM)
            for k, (te, lab, col) in enumerate([e for e in ev if e[0] <= st][-6:]):
                f.text(x0 + 0.225, 0.77 - k * 0.045, textwrap.shorten(f"{hms(te)}  {lab}", 46, placeholder="…"),
                       fontsize=12, family=MONO, color=col)
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
            if t > T1 - 0.5:
                a = fade(t, T1 - 0.5); pk = run["max_att_err_after_grace_deg"]
                lab, col = ("ATTITUDE LOSS", RED) if not ok else ("SURVIVES", GREEN)
                f.text(x0 + 0.105, 0.53, lab, fontsize=30, weight="bold", color=col, ha="center", alpha=a,
                       bbox=dict(fc=BG, ec=col, lw=2, alpha=0.9 * a))
                f.text(x0 + 0.105, 0.495, f"peak {pk:.0f}°", fontsize=16, ha="center", alpha=a)
        if t < T0 + 0.4:
            a = 1 - fade(t, T0 - 0.3)
            f.text(0.5, 0.50, "Same two faults, two runs: safe-mode policy on vs off", fontsize=34, ha="center",
                   weight="bold", alpha=a, bbox=dict(fc=BG, ec=CYAN, lw=2, alpha=0.95 * a, pad=18))
        if t > T1 + 0.8:
            a = fade(t, T1 + 0.8)
            f.text(0.5, 0.445, "The policy causes the failure: it spends its one isolation on the MILD wheel (RW0), "
                               "so the dead RW1 stays in the loop.", fontsize=17, ha="center", alpha=a,
                   bbox=dict(fc=BG, ec=AMBER, lw=1.5, alpha=0.95 * a, pad=10))
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s5 blind inference
def s5(D, T):
    s = mv.Seg("s5", {int(0.5 * T * FPS): "v2_still_blind.png"}); f = s.fig
    q = D["quote"]; first = q.split(". ")[0] + "."; rest = q[len(first):].strip()
    bm, bb = D["by_seed"]["muse"], D["by_seed"]["museblind"]
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Muse works out the hidden rule",
               "Rules-blind run: thresholds and the one-isolation limit were NOT in the prompt; "
               "only per-run outcomes were reported back",
               f"data/cmp/museblind_seed1_calls.jsonl line 5 (round {D['quote_round']}, field 'analysis') · "
               f"{D['src3']}")
        a = fade(t, 0.3)
        f.text(0.06, 0.79, "Muse Spark, verbatim:", fontsize=20, color=DIM, alpha=a)
        f.text(0.06, 0.74, textwrap.fill("“" + first + "”", 32), fontsize=36, weight="bold", color=AMBER,
               va="top", alpha=a, linespacing=1.35, style="italic")
        f.text(0.06, 0.50, textwrap.fill("“… " + rest + "”", 62), fontsize=18, color=DIM, va="top", alpha=a,
               linespacing=1.4, style="italic")
        b = fade(t, 0.42 * T)
        ax = f.add_axes([0.62, 0.30, 0.33, 0.42]); ax.set_facecolor(BG)
        xs = np.arange(3); g = np.clip((t - 0.42 * T) / 1.5, 0, 1)
        ax.bar(xs - 0.2, np.array(bm) * g, 0.38, color=ARM["muse"][1], label="Muse (rules given)", alpha=b)
        ax.bar(xs + 0.2, np.array(bb) * g, 0.38, color=ARM["museblind"][1], label="Muse-blind", alpha=b)
        ax.set_xticks(xs); ax.set_xticklabels([f"seed {k}" for k in xs], fontsize=14)
        ax.set_ylim(0, 0.62); ax.set_ylabel("violations / sim", fontsize=14); ax.tick_params(labelsize=12)
        ax.legend(fontsize=13, frameon=False, labelcolor=FG, loc="upper left")
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        f.text(0.62, 0.76, "Blind finds MORE failures, on every seed", fontsize=22, weight="bold", alpha=b)
        c = fade(t, 0.62 * T)
        f.text(0.06, 0.20, textwrap.fill("Hypothesis (not tested): giving Muse the rules anchors it to the failure "
                                         "modes it expects; without them it explores more broadly.", 110),
               fontsize=20, color=FG, alpha=c, va="top", linespacing=1.4,
               bbox=dict(fc=PANEL, ec=GRID, lw=1.2, pad=12, alpha=c))
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s6 repair (auto placeholders)
def md_table_lines(path, maxrows=9):
    L = [l.rstrip() for l in open(path) if l.strip()]
    rows = [l for l in L if l.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", l)]
    other = [l for l in L if not l.startswith("|")]
    out = []
    for r in rows[: maxrows + 1]:
        cells = [c.strip() for c in r.strip("|").split("|")]
        out.append("  ".join(textwrap.shorten(c, 34, placeholder="…").ljust(min(34, max(6, len(c)))) for c in cells[:5]))
    more = len(rows) - 1 - maxrows
    return out + ([f"… {more} more rows in {os.path.relpath(path, ROOT)}"] if more > 0 else []), other


def placeholder(f, x, y, w, h, title, path, a):
    f.add_artist(matplotlib.patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.005", fc=PANEL, ec=AMBER,
                                                   lw=2, ls="--", alpha=a, transform=f.transFigure))
    f.text(x + w / 2, y + h * 0.62, "PLACEHOLDER", fontsize=30, weight="bold", color=AMBER, ha="center", alpha=a)
    f.text(x + w / 2, y + h * 0.45, title, fontsize=20, ha="center", alpha=a)
    f.text(x + w / 2, y + h * 0.30, f"pending: {path}", fontsize=14, family=MONO, color=DIM, ha="center", alpha=a)


def s6(D, T):
    s = mv.Seg("s6", {int(0.6 * T * FPS): "v2_still_repair.png"}); f = s.fig
    rej, trend, waiv = P("data/gated/rejects_table.md"), P("plots/gated_repair_trend.png"), P("data/gated/waivers.md")
    have = {k: os.path.exists(v) for k, v in dict(rej=rej, trend=trend, waiv=waiv).items()}
    trend_img = np.asarray(Image.open(trend).convert("RGB")) if have["trend"] else None
    rej_lines = md_table_lines(rej)[0] if have["rej"] else None
    wv = md_table_lines(waiv, 6) if have["waiv"] else None
    t1, t2, t3 = 0.22 * T, 0.50 * T, 0.78 * T
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        if t < t1:
            header(f, "Repair loop: Muse proposes a patch, a gate decides",
                   "A patch is accepted only if it breaks nothing that used to pass", "src/gated_repair.py · src/gated_v2.py")
            steps = [("Muse diagnoses\nminimized failures", AMBER), ("proposes a\npolicy patch", ORANGE),
                     ("gate: replay ~3,500\nstored runs", CYAN), ("accept only if no\nclean run breaks", GREEN)]
            for k, (txt, col) in enumerate(steps):
                a = fade(t, 0.3 + 0.6 * k); x = 0.06 + k * 0.235
                f.add_artist(matplotlib.patches.FancyBboxPatch((x, 0.42), 0.19, 0.2, boxstyle="round,pad=0.01",
                                                               fc=PANEL, ec=col, lw=2.5, alpha=a, transform=f.transFigure))
                f.text(x + 0.095, 0.52, txt, fontsize=22, ha="center", va="center", alpha=a, color=FG)
                if k < 3:
                    f.text(x + 0.212, 0.52, "→", fontsize=40, color=DIM, ha="center", va="center", alpha=a)
            f.text(0.06, 0.26, "Progress is measured on FRESH held-out searches, never on the gate's own suite.",
                   fontsize=22, color=DIM, alpha=fade(t, 2.8))
        elif t < t2:
            header(f, "The gate caught patches that traded one failure for another",
                   "Strict gate: zero previously clean runs may break", "data/gated/rejects_table.md")
            a = fade(t, t1)
            if rej_lines:
                for k, l in enumerate(rej_lines):
                    f.text(0.05, 0.80 - k * 0.055, l, fontsize=15 if k else 16, family=MONO,
                           color=FG if k else DIM, weight="bold" if k == 0 else "normal", alpha=a)
            else:
                placeholder(f, 0.15, 0.25, 0.70, 0.5, "strict-gate reject table (7+ rejected patches)",
                            "data/gated/rejects_table.md", a)
        elif t < t3:
            header(f, "Fresh-search trend across repair rounds", "held-out searches, not the gate suite",
                   "plots/gated_repair_trend.png")
            a = fade(t, t2)
            if trend_img is not None:
                h_, w_ = trend_img.shape[:2]; ww = min(0.9, 0.74 * (h_ and w_ / h_) * H / W)
                axi = f.add_axes([0.5 - ww / 2, 0.10, ww, 0.74]); axi.imshow(trend_img, alpha=a); axi.set_axis_off()
            else:
                placeholder(f, 0.15, 0.25, 0.70, 0.5, "trend chart: violations per sim on fresh searches, per round",
                            "plots/gated_repair_trend.png", a)
        else:
            header(f, "Declared waivers: every broken clean run, listed and replayable",
                   "Budget mode: at most 3 previously clean runs (0.1%) may break", "data/gated/waivers.md")
            a = fade(t, t3)
            if wv:
                lines, other = wv
                for k, l in enumerate((other[:2] + lines)[:12]):
                    f.text(0.05, 0.80 - k * 0.055, l, fontsize=15, family=MONO, color=FG, alpha=a)
            else:
                placeholder(f, 0.15, 0.25, 0.70, 0.5, "waiver list (each broken run + replay command)",
                            "data/gated/waivers.md", a)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s7 prior work
def s7(D, T):
    s = mv.Seg("s7"); f = s.fig
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Prior work, and what is new here", None, "docs/ (novelty notes)")
        boxes = [("LLM-Falsifier", "arXiv 2609.20752 (2026)", "LLM-guided falsification of controllers"),
                 ("NASA Orion GN&C", "fault-management verification", "large-scale FM verification campaigns"),
                 ("Also related", "AST / DAST · JPL Nemesis · COMPASS", "stress testing, model-based FDIR checking")]
        for k, (a1, a2, a3) in enumerate(boxes):
            a = fade(t, 0.3 + 0.7 * k); x = 0.05 + k * 0.31
            f.add_artist(matplotlib.patches.FancyBboxPatch((x, 0.50), 0.28, 0.27, boxstyle="round,pad=0.01", fc=PANEL,
                                                           ec=GRID, lw=1.5, alpha=a, transform=f.transFigure))
            f.text(x + 0.02, 0.71, a1, fontsize=28, weight="bold", color=CYAN, alpha=a)
            f.text(x + 0.02, 0.65, a2, fontsize=17, color=DIM, alpha=a)
            f.text(x + 0.02, 0.57, textwrap.fill(a3, 32), fontsize=18, alpha=a, va="center")
        a = fade(t, 0.35 * T)
        f.text(0.05, 0.38, "New here:", fontsize=26, weight="bold", color=AMBER, alpha=a)
        f.text(0.05, 0.31, textwrap.fill("an open-source closed loop in which an LLM finds, minimizes and causally "
                                         "attributes (policy on/off) multi-fault counterexamples against a spacecraft "
                                         "safe-mode policy, then patches it and re-tests the patch in a physics sim.", 95),
               fontsize=24, alpha=a, va="top", linespacing=1.45)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s8 limits
def s8(D, T):
    s = mv.Seg("s8"); f = s.fig
    items = ["Static Sun direction over a run", "No momentum dumping (no magnetorquers)",
             "Self-written policy: structure follows published FDIR, thresholds are ours (docs/fdir_refs.md)",
             "One spacecraft model, 2-orbit runs, reaction-wheel / heater / torque-leak faults only"]
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf()
        header(f, "Limits", "What this does not show yet", "README.md · docs/fdir_refs.md")
        for k, it in enumerate(items):
            f.text(0.08, 0.72 - k * 0.12, "·  " + it, fontsize=28, alpha=fade(t, 0.3 + 0.6 * k))
        s.frame()
    return s.close()


# ------------------------------------------------------------------ s9 close
def s9(D, T):
    s = mv.Seg("s9"); f = s.fig
    steps = ["Find", "minimize", "explain", "repair", "re-test"]
    for i in range(int(T * FPS)):
        t = i / FPS; f.clf(); ax = f.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        for k, w in enumerate(steps):
            ax.text(0.12 + k * 0.19, 0.68, w, fontsize=40, weight="bold", color=[CYAN, AMBER, ORANGE, GREEN, FG][k],
                    alpha=fade(t, 0.2 + 0.4 * k), ha="center")
            if k < 4:
                ax.text(0.215 + k * 0.19, 0.68, "→", fontsize=40, color=DIM, alpha=fade(t, 0.4 + 0.4 * k), ha="center")
        a = fade(t, 2.4)
        ax.text(0.5, 0.45, f"python3 demo/replay_headline_v2.py {HL_KEY}   # policy on vs off", fontsize=22,
                family=MONO, ha="center", color=GREEN, alpha=a, bbox=dict(fc=PANEL, ec=GRID, lw=1.5, pad=20, alpha=a))
        ax.text(0.5, 0.28, REPO_URL, fontsize=30, ha="center", color=FG, alpha=a)
        ax.text(0.5, 0.14, "Basilisk · Meta Muse Spark · CMA-ES & random baselines · minimizer · gated repair",
                fontsize=18, ha="center", color=DIM, alpha=a)
        ax.text(0.5, 0.07, "FaultForge", fontsize=28, ha="center", color=CYAN, weight="bold", alpha=a)
        s.frame()
    return s.close()


SEGS = dict(s1=s1, s2=s2, s3=s3, s4=s4, s5=s5, s6=s6, s7=s7, s8=s8, s9=s9)


def _run(k):
    T = seg_durs()[k]
    return k, SEGS[k](load_data(), T)


def mux(durs):
    ids = list(SEGS)
    lst = os.path.join(BUILD, "list.txt")
    open(lst, "w").write("".join(f"file '{k}.mp4'\n" for k in ids))
    vid = os.path.join(BUILD, "video_only.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", vid],
                   check=True)
    # audio: each segment = lead silence + VO, padded/trimmed to the segment length, then concatenated
    parts, inputs = [], []
    for n, k in enumerate(ids):
        wav = os.path.join(HERE, "vo", f"{k}.wav"); T = durs[k]
        if os.path.exists(wav):
            inputs += ["-i", wav]
            parts.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                         f"adelay={int(v2_script.VO_LEAD * 1000)}:all=1,apad,atrim=0:{T:.3f}[a{n}]")
        else:
            inputs += ["-f", "lavfi", "-t", f"{T:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            parts.append(f"[{n}:a]atrim=0:{T:.3f}[a{n}]")
    fc = ";".join(parts) + ";" + "".join(f"[a{n}]" for n in range(len(ids))) + f"concat=n={len(ids)}:v=0:a=1[aout]"
    aud = os.path.join(BUILD, "audio.m4a")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[aout]", "-c:a",
                    "aac", "-b:a", "160k", aud], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", vid, "-i", aud, "-map", "0:v", "-map", "1:a", "-c:v",
                    "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", OUT], check=True)
    d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                       "default=nw=1:nk=1", OUT]).decode())
    print(f"wrote {OUT}  {d:.1f} s ({int(d) // 60}:{int(d) % 60:02d})")
    assert d < 180, "video is over 3:00"


if __name__ == "__main__":
    durs = seg_durs(); tot = sum(durs.values())
    print("segments:", {k: round(v, 1) for k, v in durs.items()}, f"total {tot:.1f} s")
    assert tot <= v2_script.MAX_TOTAL, f"total {tot:.1f} s exceeds cap"
    only = [a for a in sys.argv[1:] if a in SEGS] or list(SEGS)
    only = sorted(only, key=lambda k: -durs[k])          # longest first
    with Pool(min(len(only), int(os.environ.get("FF_RENDER_WORKERS", "3")))) as p:
        for name, n in p.imap_unordered(_run, only):
            print(name, n, "frames", round(n / FPS, 1), "s", flush=True)
    mux(durs)
