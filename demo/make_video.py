"""Build the FaultForge first-cut demo video from repo data only.

    python demo/replay_attitude.py      # once: re-runs the headline case with attitude logging -> demo/data/
    python demo/make_video.py           # renders 6 segments in parallel, concatenates -> demo/faultforge_demo_v1.mp4

Every number on screen is read from data/cmp/summary.json, data/cmp/*_seed1.jsonl, data/grid.jsonl,
data/repair/*.json or demo/data/headline_*.csv (replays); nothing is typed in by hand except labels.
"""
import json, os, subprocess, sys, textwrap
from multiprocessing import Pool

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import ff_sim  # noqa: E402

BUILD = os.path.join(HERE, "build"); os.makedirs(BUILD, exist_ok=True)
FPS, W, H = 30, 1920, 1080
BG, PANEL, GRID, FG, DIM = "#0a0e14", "#101823", "#1d2a38", "#e6edf3", "#7d8b99"
CYAN, AMBER, ORANGE, GREY, RED, GREEN = "#39d0ff", "#ffb000", "#ff7a3d", "#8a96a3", "#ff4d5e", "#3ddc84"
ARM = {"muse": ("Muse", AMBER), "museblind": ("Muse-blind", ORANGE), "cmaes": ("CMA-ES", CYAN), "random": ("random", GREY)}
plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": FG, "axes.labelcolor": DIM, "xtick.color": DIM,
                     "ytick.color": DIM, "axes.edgecolor": GRID, "axes.facecolor": PANEL, "figure.facecolor": BG,
                     "savefig.facecolor": BG})
MONO = "DejaVu Sans Mono"


def J(p):
    return json.load(open(os.path.join(ROOT, p)))


def jl(p):
    return [json.loads(l) for l in open(os.path.join(ROOT, p))]


# ------------------------------------------------------------------ data (all from repo files)
def load_data():
    D = {}
    grid = jl("data/grid.jsonl"); D["grid"] = [bool(r["violated"]) for r in grid]
    S = J("data/cmp/summary.json"); D["S"] = S
    D["race"] = {}
    for a in ARM:
        rs = sorted(jl(f"data/cmp/{a}_seed1.jsonl"), key=lambda r: r["id"])
        n = S["arms"][a]["per_seed"]["1"]["sims"]
        v = np.array([bool(r["violated"]) for r in rs[:n]], int)
        assert v.sum() == S["arms"][a]["per_seed"]["1"]["violations"], a
        D["race"][a] = np.cumsum(v)
    D["union"] = {a: len(S["arms"][a]["union_patterns_fine"]) for a in ARM}
    D["union_pi"] = {a: len(S["arms"][a]["union_patterns_policy_induced"]) for a in ARM}
    D["fx"] = J("data/repair/fixes_v2_summary.json"); D["rg"] = J("data/repair/regress_v2_summary.json")
    D["rg3"] = J("data/repair/regress_v3_summary.json"); D["fx3"] = J("data/repair/fixes_v3_summary.json")
    D["s2"] = J("data/repair/summary_v2.json"); D["r1"] = J("data/repair/round1_response.json")
    D["pol2"] = J("data/repair/policy_v2.json"); D["v1abs"] = ff_sim.POLICY["fdir_abs_Nm"]
    D["hl"] = json.load(open(os.path.join(HERE, "data", "headline_runs.json")))
    D["tel"] = {t: pd.read_csv(os.path.join(HERE, "data", f"headline_{t}.csv")) for t in ("v1", "v1_nopolicy", "v2")}
    D["cfg"] = ff_sim.CFG
    # where the headline case came from (summary.json pattern index)
    for p, v in S["patterns"].items():
        for a, l in v.items():
            for x in l:
                if x["key"] == D["hl"]["key"]:
                    D["hl_src"] = (a, x["seed"], x["id"])
    D["hl_min"] = next(r for r in jl("data/cmp/minimized.jsonl") if r["key"] == D["hl"]["key"])
    return D


def _n(x):
    return x if isinstance(x, (int, float)) else x


# ------------------------------------------------------------------ writer
class Seg:
    def __init__(self, name, stills=None):
        self.name, self.k, self.stills = name, 0, stills or {}
        self.fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                                   "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                                   "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
                                   os.path.join(BUILD, f"{name}.mp4")], stdin=subprocess.PIPE)

    def frame(self):
        self.fig.canvas.draw()
        buf = np.asarray(self.fig.canvas.buffer_rgba())
        assert buf.shape[:2] == (H, W), buf.shape
        self.p.stdin.write(buf.tobytes())
        if self.k in self.stills:
            Image.fromarray(buf[:, :, :3].copy()).save(os.path.join(HERE, self.stills[self.k]))
        self.k += 1

    def close(self):
        self.p.stdin.close(); self.p.wait(); plt.close(self.fig)
        return self.k


def fade(t, t0, d=0.6):
    return float(np.clip((t - t0) / d, 0, 1))


def header(fig, title, sub=None, src=None, a=1.0):
    fig.text(0.04, 0.935, title, fontsize=34, weight="bold", alpha=a)
    if sub:
        fig.text(0.04, 0.895, sub, fontsize=17, color=DIM, alpha=a)
    if src:
        fig.text(0.04, 0.025, "data: " + src, fontsize=12, color=DIM, family=MONO, alpha=a)
    fig.text(0.96, 0.025, "FaultForge", fontsize=13, color=CYAN, ha="right", weight="bold", alpha=0.8 * a)
    fig.add_artist(plt.Line2D([0.04, 0.96], [0.875, 0.875], color=GRID, lw=1.5, alpha=a))


# ------------------------------------------------------------------ 1. title (8 s)
def seg1(D):
    s = Seg("s1"); f = s.fig
    rng = np.random.default_rng(3); sx, sy, ss = rng.random(260), rng.random(260), rng.random(260) ** 3 * 14
    for i in range(8 * FPS):
        t = i / FPS; f.clf(); ax = f.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.scatter(sx, (sy + 0.004 * t) % 1, s=ss, c="#9fb3c8", alpha=0.35, lw=0)
        a1, a2, a3 = fade(t, 0.3), fade(t, 1.6), fade(t, 3.0)
        ax.text(0.5, 0.62, "FaultForge", ha="center", fontsize=96, weight="bold", color=CYAN, alpha=a1)
        ax.text(0.5, 0.52, "AI-directed discovery of spacecraft multi-fault failures", ha="center", fontsize=40,
                alpha=a1)
        ax.text(0.5, 0.38, "Pre-existing: Basilisk simulator (open source).", ha="center", fontsize=24, color=DIM,
                alpha=a2)
        ax.text(0.5, 0.33, "Built this week: fault harness, safe-mode policy, Muse-guided search, minimizer, repair loop.",
                ha="center", fontsize=24, color=FG, alpha=a2)
        ax.text(0.5, 0.12, "CBxMeta AI-Hack  ·  first-cut demo  ·  all numbers from the repo's data files",
                ha="center", fontsize=17, color=DIM, alpha=a3)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ 2. problem (22 s)
def seg2(D):
    s = Seg("s2", {int(11 * FPS): "still_1_single_fault_grid.png"}); f = s.fig
    g = np.array(D["grid"]); n = len(g); side = int(np.ceil(np.sqrt(n))); nfail = int(g.sum())
    rg = D["rg"]["all_stored_v1_search_runs"]
    for i in range(22 * FPS):
        t = i / FPS; f.clf()
        header(f, "The problem: faults are tested one at a time",
               "A CubeSat safe-mode / FDIR policy, checked the usual way: every single fault, one run each",
               "data/grid.jsonl, data/repair/regress_v2_summary.json")
        k = int(n * np.clip((t - 0.5) / 7.0, 0, 1))
        img = np.zeros((side, side, 4)); img[..., :3] = matplotlib.colors.to_rgb(GRID); img[..., 3] = 1
        for j in range(k):
            img[j // side, j % side, :3] = matplotlib.colors.to_rgb(RED if g[j] else GREEN)
        ax = f.add_axes([0.05, 0.12, 0.40, 0.71]); ax.imshow(img, interpolation="nearest"); ax.set_axis_off()
        passed = int((~g[:k]).sum())
        f.text(0.05, 0.085, f"single-fault grid + nominal runs: {k:3d} / {n}   pass {passed}   fail {k - passed}",
               fontsize=18, family=MONO, color=DIM)
        a = fade(t, 8.2)
        f.text(0.50, 0.70, f"{n - nfail} / {n}", fontsize=110, weight="bold", color=GREEN, alpha=a)
        f.text(0.50, 0.64, "single-fault cases survive. Looks safe.", fontsize=28, alpha=a)
        a = fade(t, 12.0)
        f.text(0.50, 0.50, "But real failures stack.", fontsize=40, weight="bold", color=AMBER, alpha=a)
        f.text(0.50, 0.38, textwrap.fill("A mild fault, then a severe one hours later, and the policy's own "
                                          "response decides whether the spacecraft survives.", 46),
               fontsize=24, color=FG, alpha=a, linespacing=1.4)
        a = fade(t, 16.5)
        f.text(0.50, 0.22, f"{rg['v1_violating']} of {rg['n']}", fontsize=56, weight="bold", color=RED, alpha=a)
        f.text(0.50, 0.15, "stored multi-fault search runs (all arms) end in a safety violation", fontsize=22,
               color=FG, alpha=a)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ 3. search race (45 s)
def seg3(D):
    s = Seg("s3", {int(33.5 * FPS): "still_2_search_race.png"}); f = s.fig
    S = D["S"]; race = D["race"]; N = max(len(v) for v in race.values())
    T_RACE = 32.0
    for i in range(45 * FPS):
        t = i / FPS; f.clf()
        if t < 34.0:
            header(f, "Search race: who finds failures faster?",
                   "Seed 1 · 300 simulations per arm · same fault space · same budget",
                   "data/cmp/{muse,museblind,cmaes,random}_seed1.jsonl")
            x = min(N, N * min(1, t / T_RACE) ** 1.0)
            ax = f.add_axes([0.06, 0.12, 0.60, 0.72])
            ax.grid(color=GRID, lw=0.8)
            for a, (lab, c) in ARM.items():
                y = race[a]; m = int(np.floor(x))
                xs = np.arange(1, m + 1)
                ax.plot(xs, y[:m], color=c, lw=3.2 if a == "muse" else 2.4, ls="--" if a == "museblind" else "-")
                if m:
                    ax.plot([m], [y[m - 1]], "o", color=c, ms=9)
            ax.set_xlim(0, N); ax.set_ylim(0, max(v[-1] for v in race.values()) * 1.08)
            ax.set_xlabel("simulations run", fontsize=16); ax.set_ylabel("cumulative safety violations", fontsize=16)
            ax.tick_params(labelsize=13)
            m = int(np.floor(x))
            f.text(0.70, 0.80, f"sims: {m:3d} / {N}", fontsize=26, family=MONO)
            for j, (a, (lab, c)) in enumerate(ARM.items()):
                yy = 0.70 - j * 0.10
                v = int(race[a][m - 1]) if m else 0
                f.text(0.70, yy, lab, fontsize=26, color=c, weight="bold")
                f.text(0.92, yy, f"{v:3d}", fontsize=30, color=c, family=MONO, ha="right", weight="bold")
            f.text(0.70, 0.27, textwrap.fill("Muse: Meta Muse proposes the next fault scenarios from results so far "
                                             "(policy rules visible). Muse-blind: rules hidden. CMA-ES: evolutionary "
                                             "optimizer on a safety-margin objective. random: uniform sampling.", 46),
                   fontsize=14, color=DIM, va="top", linespacing=1.45)
        else:
            a0 = fade(t, 34.0, 0.5); g = np.clip((t - 34.3) / 1.5, 0, 1)
            header(f, "Across seeds: more failures, and more kinds of failure",
                   "Equal budget per seed · means over seeds 0-2 (Muse-blind: seed 1 only)",
                   "data/cmp/summary.json  (arms.*.mean, arms.*.union_patterns_*)", a=a0)
            arms = ["muse", "museblind", "cmaes", "random"]
            vps = [S["arms"][a]["mean"]["violations_per_sim"] for a in arms]
            pat = [D["union"][a] for a in arms]; pi = [D["union_pi"][a] for a in arms]
            for col, (vals, ttl, fmt) in enumerate([(vps, "violations per simulation (mean)", "{:.3f}"),
                                                     (pat, "distinct failure patterns (all seeds)", "{:d}")]):
                ax = f.add_axes([0.15 + col * 0.47, 0.16, 0.30, 0.62]); ax.set_facecolor(BG)
                yy = np.arange(len(arms))[::-1]
                ax.barh(yy, np.array(vals) * g, color=[ARM[a][1] for a in arms], height=0.62, alpha=a0)
                if col == 1:
                    ax.barh(yy, np.array(pi) * g, color="none", edgecolor=FG, hatch="//", height=0.62, lw=0,
                            alpha=0.35 * a0)
                for k, a in enumerate(arms):
                    ax.text(-0.02 * max(vals), yy[k], ARM[a][0], ha="right", va="center", fontsize=22,
                            color=ARM[a][1], weight="bold", alpha=a0)
                    lab = fmt.format(vals[k]) + (f"   ({pi[k]} policy-induced)" if col == 1 else "")
                    ax.text(vals[k] * g + 0.02 * max(vals), yy[k], lab, va="center", fontsize=22, family=MONO,
                            alpha=a0 * g)
                ax.set_xlim(0, max(vals) * (2.1 if col == 1 else 1.45)); ax.set_axis_off()
                f.text(0.15 + col * 0.47, 0.80, ttl, fontsize=22, color=DIM, alpha=a0)
            f.text(0.06, 0.09, textwrap.fill("policy-induced = the same faults do not violate with the policy "
                                             "disabled, i.e. the safe-mode logic itself causes the failure.", 120),
                   fontsize=15, color=DIM, alpha=a0)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ 3D helpers
def mrp2dcm(sg):
    s = np.asarray(sg, float); s2 = s @ s
    X = np.array([[0, -s[2], s[1]], [s[2], 0, -s[0]], [-s[1], s[0], 0]])
    return np.eye(3) + (8 * X @ X - 4 * (1 - s2) * X) / (1 + s2) ** 2


def body_faces():
    bx, by, bz = 0.25, 0.25, 0.45
    v = np.array([[x, y, z] for x in (-bx, bx) for y in (-by, by) for z in (-bz, bz)])
    idx = [[0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4], [1, 3, 7, 5]]
    box = [v[i] for i in idx]
    pan = [np.array([[bx, -by * 0.9, -bz * 0.9], [bx + 0.9, -by * 0.9, -bz * 0.9], [bx + 0.9, -by * 0.9, bz * 0.9],
                     [bx, -by * 0.9, bz * 0.9]]),
           np.array([[-bx, -by * 0.9, -bz * 0.9], [-bx - 0.9, -by * 0.9, -bz * 0.9],
                     [-bx - 0.9, -by * 0.9, bz * 0.9], [-bx, -by * 0.9, bz * 0.9]])]
    return box, pan


BOX, PAN = body_faces()


def draw_sc(ax, sigma, ok):
    C = mrp2dcm(sigma)                           # [BR]: R-frame vector -> B-frame; vertices in R: C^T v_B
    rot = lambda P: P @ C
    ax.add_collection3d(Poly3DCollection([rot(p) for p in BOX], facecolor="#c9d3dd", edgecolor="#6b7785",
                                         lw=0.8, alpha=0.95))
    ax.add_collection3d(Poly3DCollection([rot(p) for p in PAN], facecolor="#1f4e8c", edgecolor=CYAN, lw=1.0,
                                         alpha=0.95))
    b = np.array([0, 0, 0.95]) @ C              # body +z (payload boresight)
    ax.plot([0, 0], [0, 0], [0, 1.1], color=FG, lw=1.6, ls=":", zorder=10)   # commanded boresight
    ax.plot([0, b[0] * 1.15], [0, b[1] * 1.15], [0, b[2] * 1.15], color=GREEN if ok else RED, lw=3.5, zorder=11)
    ax.set_xlim(-0.8, 0.8); ax.set_ylim(-0.8, 0.8); ax.set_zlim(-0.8, 0.8)
    ax.set_axis_off(); ax.view_init(elev=8, azim=-30)
    try:
        ax.set_box_aspect((1, 1, 1))
    except Exception:
        pass


def short(msg):
    if msg.startswith("FAULT"):
        d = json.loads(msg[msg.index("{"):])
        return f"FAULT  RW{d['wheel']} {d['type']} sev {d['severity']:.2f}", AMBER
    if "isolated" in msg:
        w = msg.split("wheel ")[1].split()[0]; r = msg.split("residual ")[1].rstrip(")")
        return f"FDIR   isolates RW{w}  (residual {r})", CYAN
    if "-> SAFE" in msg:
        return "POLICY -> SAFE MODE (sun-point, payload off)", ORANGE
    if "-> NOMINAL" in msg:
        return "POLICY -> NOMINAL", GREEN
    return msg[:50], FG


def events(run, cfg):
    ev = [(t, *short(m)) for t, m in run["policy_log"]]
    for k, tv in run["violations"].items():
        ev.append((tv, f"VIOLATION  {k}  (> {cfg['att_err_bound_deg']:.0f} deg for "
                       f"{cfg['att_err_max_dur_s'] / 60:.0f} min)", RED))
    return sorted(ev)


def hms(t):
    t = int(t); return f"T+{t // 3600:d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


# ------------------------------------------------------------------ 4. headline counterexample (45 s)
def seg4(D):
    s = Seg("s4", {int(36 * FPS): "still_3_headline_split.png"}); f = s.fig
    cfg = D["cfg"]; hl = D["hl"]; a_src = D["hl_src"]; mn = D["hl_min"]
    runs = [("v1", "SAFE-MODE POLICY ON (v1)"), ("v1_nopolicy", "POLICY OFF (same faults)")]
    tel = {k: D["tel"][k] for k, _ in runs}; Tend = float(tel["v1"].t_s.max())
    T0, T1 = 3.0, 40.0
    for i in range(45 * FPS):
        t = i / FPS; f.clf()
        header(f, f"Headline counterexample {hl['key']}",
               f"Found by the {ARM[a_src[0]][0]} arm (seed {a_src[1]}, run {a_src[2]}), minimized from "
               f"{mn['n_faults_before']} faults to {mn['n_faults_after']} in {mn['minimization_sims']} sims · "
               f"Basilisk replay, 2 orbits", "demo/data/headline_{v1,v1_nopolicy}.csv (demo/replay_attitude.py), "
                                              "data/repair/headline_v2.json")
        st = Tend * np.clip((t - T0) / (T1 - T0), 0, 1)
        speed = Tend / (T1 - T0)
        f.text(0.96, 0.935, hms(st), fontsize=34, family=MONO, ha="right", color=CYAN)
        f.text(0.96, 0.898, f"sim time  ×{speed:.0f}", fontsize=15, family=MONO, ha="right", color=DIM)
        for c, (tag, ttl) in enumerate(runs):
            d = tel[tag]; run = hl[tag]; ev = events(run, cfg)
            j = int(np.searchsorted(d.t_s.values, st, side="right")) - 1; j = max(j, 0)
            row = d.iloc[j]; x0 = 0.04 + c * 0.48
            viol_now = [e for e in ev if e[2] == RED and e[0] <= st]
            ok = not viol_now
            f.text(x0, 0.835, ttl, fontsize=22, weight="bold", color=FG)
            mode = "SAFE" if row.safe_mode else "NOMINAL"
            iso = [k for k in range(4) if row[f"rw{k}_avail"] == 0]
            f.text(x0, 0.805, f"mode {mode:<8s} isolated {('RW' + ','.join(map(str, iso))) if iso else '-':<6s}"
                              f" att err {row.att_err_deg:5.1f}°", fontsize=15, family=MONO,
                   color=ORANGE if row.safe_mode else DIM)
            ax3 = f.add_axes([x0 - 0.01, 0.47, 0.22, 0.33], projection="3d"); ax3.set_facecolor(BG)
            draw_sc(ax3, [row.sBR1, row.sBR2, row.sBR3], row.att_err_deg < cfg["att_err_bound_deg"])
            f.text(x0 + 0.005, 0.475, "spacecraft vs. commanded attitude (dotted = commanded boresight)", fontsize=12, color=DIM)
            # event ticker
            shown = [e for e in ev if e[0] <= st][-6:]
            for k, (te, lab, col) in enumerate(shown):
                f.text(x0 + 0.225, 0.77 - k * 0.045, f"{hms(te)}  {lab}", fontsize=13, family=MONO, color=col)
            # strips
            m = d.t_s.values <= st
            axa = f.add_axes([x0 + 0.02, 0.28, 0.42, 0.16])
            axa.axhline(cfg["att_err_bound_deg"], color=RED, lw=1, ls="--")
            axa.text(Tend * 0.99, cfg["att_err_bound_deg"] + 3, "30° bound", color=RED, fontsize=11, ha="right")
            axa.plot(d.t_s.values[m], d.att_err_deg.values[m], color=AMBER, lw=1.8)
            axa.set_xlim(0, Tend); axa.set_ylim(0, 90); axa.set_ylabel("att err [deg]", fontsize=12)
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
                a = fade(t, T1 - 0.5)
                if not ok:
                    f.text(x0 + 0.105, 0.53, "ATTITUDE LOSS", fontsize=30, weight="bold", color=RED, ha="center",
                           alpha=a, bbox=dict(fc=BG, ec=RED, lw=2, alpha=0.9 * a))
                else:
                    late = d[d.t_s > 7000].att_err_deg.max()
                    f.text(x0 + 0.105, 0.53, "SURVIVES", fontsize=30, weight="bold", color=GREEN, ha="center",
                           alpha=a, bbox=dict(fc=BG, ec=GREEN, lw=2, alpha=0.9 * a))
                    f.text(x0 + 0.105, 0.495, f"peak {late:.1f}° after the 2nd fault", fontsize=15, ha="center",
                           alpha=a)
        if t < T0 + 0.5:
            a = 1 - fade(t, T0 - 0.3)
            f.text(0.5, 0.50, "Same two faults, two runs: safe-mode policy on vs. off", fontsize=34, ha="center",
                   weight="bold", alpha=a, bbox=dict(fc=BG, ec=CYAN, lw=2, alpha=0.95 * a, pad=18))
        if t > T1 + 1.0:
            a = fade(t, T1 + 1.0)
            f.text(0.5, 0.445, "The policy causes the failure: FDIR spends its one isolation on the MILD wheel (RW1), "
                               "leaving the severe one (RW2) in the loop.", fontsize=17, ha="center", alpha=a,
                   bbox=dict(fc=BG, ec=AMBER, lw=1.5, alpha=0.95 * a, pad=10))
        s.frame()
    return s.close()


# ------------------------------------------------------------------ 5. repair loop (36 s)
def seg5(D):
    s = Seg("s5", {int(22.5 * FPS): "still_4_repair_v1_vs_v2.png"}); f = s.fig
    r1 = D["r1"]; diag = r1["parsed"]["diagnosis"]; ch = r1["accepted_change"]
    key = list(ch)[0]; new = ch[key]; old = D["v1abs"]
    q = diag.split(" System is left")[0] + " … causing attitude_loss and wheel_saturation that 4 degraded wheels avoid."
    assert diag.endswith("causing attitude_loss and wheel_saturation that 4 degraded wheels avoid.")
    fx = D["fx"]["in_scope_policy_induced"]; rg = D["rg"]; ms = D["s2"]["search"]["muse"]
    newpat = len(set(ms["v2"]["patterns_policy_induced_in_scope"]) - set(ms["v1"]["patterns_policy_induced_in_scope"]))
    rg3 = D["rg3"]["all_stored_v1_search_runs"]; fx3 = D["fx3"]["in_scope_policy_induced"]
    cfg = D["cfg"]; hl = D["hl"]
    for i in range(36 * FPS):
        t = i / FPS; f.clf()
        if t < 13:
            header(f, "Repair loop, round 1: Muse explains the failures and proposes a fix",
                   f"Input: {r1['n_cases_in_scope']} in-scope policy-induced minimized counterexamples + policy logic "
                   f"· model {r1['model']}", "data/repair/round1_response.json, data/repair/policy_v2.json")
            a = fade(t, 0.4)
            f.text(0.07, 0.78, "Muse diagnosis (verbatim, shortened):", fontsize=20, color=DIM, alpha=a)
            f.text(0.07, 0.74, textwrap.fill("“" + q + "”", 70), fontsize=27, va="top", alpha=a, linespacing=1.5,
                   style="italic")
            if t > 7.5:
                a = fade(t, 7.5)
                f.text(0.07, 0.30, "Proposed change (whitelisted parameter, bounds-checked):", fontsize=20, color=DIM,
                       alpha=a)
                f.text(0.07, 0.20, f"{key}:  {old:.0e}  →  {new:.0e} Nm", fontsize=52, family=MONO, color=CYAN,
                       weight="bold", alpha=a)
                f.text(0.07, 0.13, "filters mild-friction residuals; severe faults still trip the detector",
                       fontsize=18, color=DIM, alpha=a)
        elif t < 24:
            header(f, "Re-test the headline case: v1 vs v2", f"Same faults · only {key} changed",
                   "demo/data/headline_{v1,v2}.csv, data/repair/headline_v2.json")
            Tend = float(D["tel"]["v1"].t_s.max()); st = Tend * np.clip((t - 13.5) / 8.0, 0, 1)
            f.text(0.96, 0.935, hms(st), fontsize=34, family=MONO, ha="right", color=CYAN)
            for r, (tag, lab, col) in enumerate([("v1", "v1  (fdir_abs 3e-4)", RED), ("v2", "v2  (fdir_abs 6e-4)", GREEN)]):
                d = D["tel"][tag]; m = d.t_s.values <= st
                ax = f.add_axes([0.06, 0.50 - r * 0.36, 0.54, 0.30])
                ax.axhline(cfg["att_err_bound_deg"], color=RED, lw=1, ls="--")
                ax.plot(d.t_s.values[m], d.att_err_deg.values[m], color=AMBER, lw=2)
                ax.set_xlim(0, Tend); ax.set_ylim(0, 90); ax.set_ylabel("att err [deg]", fontsize=13)
                ax.tick_params(labelsize=11); ax.axvspan(0, cfg["att_grace_s"], color=GRID, alpha=0.5)
                ax.set_title(lab, loc="left", fontsize=20, color=FG, weight="bold")
                ev = events(hl[tag] if tag != "v2" else hl["v2"], cfg); y = 0.78 - r * 0.36
                shown = [e for e in ev if e[0] <= st]
                for te, l2, c2 in shown:
                    ax.axvline(te, color=c2, lw=1.2)
                for k, (te, l2, c2) in enumerate(shown[-4:]):
                    f.text(0.62, y - k * 0.045, f"{hms(te)}  {l2}", fontsize=12.5, family=MONO, color=c2)
                if t > 21.6:
                    a = fade(t, 21.6)
                    late = d[d.t_s > 7000].att_err_deg.max()
                    txt = "ATTITUDE LOSS" if hl[tag]["violations"] else f"HOLDS · peak {late:.1f}° after 2nd fault"
                    f.text(0.62, y - 0.22, txt, fontsize=21, weight="bold", color=RED if hl[tag]["violations"] else GREEN,
                           alpha=a)
        elif t < 30:
            header(f, "Did the fix hold?", "Replays of stored cases under v2",
                   "data/repair/fixes_v2_summary.json, data/repair/regress_v2_summary.json")
            a = fade(t, 24.2); b = fade(t, 25.8)
            f.text(0.07, 0.62, f"{fx['target_fixed']} / {fx['n']}", fontsize=110, weight="bold", color=GREEN, alpha=a)
            f.text(0.07, 0.55, f"in-scope minimized counterexamples fixed ({fx['target_fixed'] / fx['n']:.0%})",
                   fontsize=26, alpha=a)
            gg = rg["grid_single_fault_plus_nominal"]
            f.text(0.55, 0.62, f"{gg['regressions']}", fontsize=110, weight="bold", color=GREEN, alpha=b)
            f.text(0.55, 0.55, f"regressions on {gg['n']} single-fault + nominal runs", fontsize=26, alpha=b)
        else:
            header(f, "The honest part: re-testing finds new failures", "Fresh search against v2 vs. v1 (seed 1)",
                   "data/repair/summary_v2.json, data/repair/regress_v{2,3}_summary.json, data/repair/fixes_v3_summary.json")
            a = fade(t, 30.2); b = fade(t, 31.8); c = fade(t, 33.4)
            f.text(0.07, 0.66, f"{ms['v2']['violations']} violations in {ms['v2']['sims']} sims against v2",
                   fontsize=46, weight="bold", color=AMBER, alpha=a)
            f.text(0.07, 0.60, f"(v1: {ms['v1']['violations']} in the same arm's first {ms['v1']['sims']})  ·  "
                               f"{newpat} new in-scope policy-induced patterns", fontsize=24, alpha=a)
            ra = rg["all_stored_v1_search_runs"]
            f.text(0.07, 0.46, f"Full multi-fault replays: {ra['regressions']} regressions, {ra['fixed']} fixes "
                               f"in {ra['n']} stored runs", fontsize=26, color=FG, alpha=b)
            f.text(0.07, 0.32, textwrap.fill(
                f"Round 2 (Muse's swap rule, v3): {fx3['target_fixed']}/{fx3['n']} minimized fixes, but "
                f"{rg3['regressions']} full-run regressions, so it was rejected and v2 kept.", 80),
                fontsize=22, color=DIM, alpha=c, va="top", linespacing=1.4)
        s.frame()
    return s.close()


# ------------------------------------------------------------------ 6. closing (13 s)
def seg6(D):
    s = Seg("s6"); f = s.fig
    steps = ["Find", "minimize", "explain", "repair", "re-test"]
    for i in range(13 * FPS):
        t = i / FPS; f.clf(); ax = f.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        for k, w in enumerate(steps):
            a = fade(t, 0.3 + 0.5 * k)
            ax.text(0.12 + k * 0.19, 0.66, w, fontsize=40, weight="bold",
                    color=[CYAN, AMBER, ORANGE, GREEN, FG][k], alpha=a, ha="center")
            if k < 4:
                ax.text(0.215 + k * 0.19, 0.66, "→", fontsize=40, color=DIM, alpha=fade(t, 0.55 + 0.5 * k), ha="center")
        a = fade(t, 3.2)
        ax.text(0.5, 0.53, "Every result replayable.", fontsize=40, ha="center", alpha=a)
        a = fade(t, 4.6)
        ax.text(0.5, 0.38, "python src/replay.py data/repair/headline_v2.json               # v1: attitude loss\n"
                           "python src/replay.py data/repair/headline_v2.json --policy v2   # v2: holds",
                fontsize=22, family=MONO, ha="center", va="center", multialignment="left", color=GREEN, alpha=a, linespacing=1.8,
                bbox=dict(fc=PANEL, ec=GRID, lw=1.5, pad=22, alpha=a))
        a = fade(t, 6.5)
        ax.text(0.5, 0.18, "Basilisk sim · Meta Muse · CMA-ES & random baselines · counterexample minimizer · "
                           "repair loop", fontsize=18, ha="center", color=DIM, alpha=a)
        ax.text(0.5, 0.12, "FaultForge", fontsize=30, ha="center", color=CYAN, weight="bold", alpha=a)
        s.frame()
    return s.close()


SEGS = [seg1, seg2, seg3, seg4, seg5, seg6]


def _run(k):
    return SEGS[k].__name__, SEGS[k](load_data())


if __name__ == "__main__":
    only = [int(a) for a in sys.argv[1:]] or list(range(len(SEGS)))
    with Pool(len(only)) as p:
        for name, n in p.imap_unordered(_run, only):
            print(name, n, "frames", n / FPS, "s", flush=True)
    lst = os.path.join(BUILD, "list.txt")
    open(lst, "w").write("".join(f"file 's{k + 1}.mp4'\n" for k in range(len(SEGS))))
    out = os.path.join(HERE, "faultforge_demo_v1.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                    "-movflags", "+faststart", out], check=True)
    print("wrote", out)
