"""Generate demo v2 narration, one WAV per segment, from demo/v2_script.py.

    python3 demo/make_vo.py [--engine edge|piper] [--voice en-US-AndrewNeural] [--rate +0%] [--force]

edge  = edge-tts (free Microsoft neural voices, needs network).  piper = fully offline (en_US-ryan-high).
Default: edge, falls back to piper per segment if edge fails. Bracketed text "[...]" is a placeholder and is
not spoken. Outputs demo/vo/<id>.wav (24 kHz mono) and demo/vo/durations.json; skips segments whose text and
voice are unchanged (hash in durations.json) unless --force.
TTS binaries: $FF_TTS_BIN (default /workspace/ttsvenv/bin) holding edge-tts and piper; piper voice at
$FF_PIPER_VOICE (default /workspace/piper_voices/en_US-ryan-high.onnx).
"""
import argparse, hashlib, time, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import importlib  # noqa: E402

# --script v2 (default, demo/v2_script.py -> demo/vo/), v3 (demo/v3_script.py -> demo/vo_v3/) or v4 (-> demo/vo_v4/)
_SCRIPT = sys.argv[sys.argv.index("--script") + 1] if "--script" in sys.argv else "v2"
v2_script = importlib.import_module(f"{_SCRIPT}_script")  # name kept so the code below is unchanged
VO = os.path.join(HERE, "vo" if _SCRIPT == "v2" else f"vo_{_SCRIPT}"); os.makedirs(VO, exist_ok=True)
BIN = os.environ.get("FF_TTS_BIN", "/workspace/ttsvenv/bin")
PV = os.environ.get("FF_PIPER_VOICE", "/workspace/piper_voices/en_US-ryan-high.onnx")


def spoken(text):
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", "", text)).strip()


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                          "default=nw=1:nk=1", path]).decode())


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "24000", "-af",
                    "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5",
                    dst], check=True)


def tts(engine, text, dst, voice, rate):
    with tempfile.TemporaryDirectory() as td:
        if engine == "edge":
            raw = os.path.join(td, "a.mp3")
            for attempt in range(4):  # edge-tts occasionally drops a connection; retry before falling back
                try:
                    subprocess.run([os.path.join(BIN, "edge-tts"), "--voice", voice, f"--rate={rate}", "--text",
                                    text, "--write-media", raw], check=True, timeout=120, capture_output=True)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(3 * (attempt + 1))
        else:
            raw = os.path.join(td, "a.wav")
            subprocess.run([os.path.join(BIN, "piper"), "-m", PV, "-f", raw, "--length_scale", "1.0"],
                           input=text.encode(), check=True, timeout=300, capture_output=True)
        to_wav(raw, dst)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="edge", choices=["edge", "piper"])
    ap.add_argument("--voice", default="en-US-AndrewNeural"); ap.add_argument("--rate", default="+0%")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--script", default="v2", choices=["v2", "v3", "v4"])
    a = ap.parse_args()
    dj = os.path.join(VO, "durations.json")
    old = json.load(open(dj)) if os.path.exists(dj) else {}
    out = {}
    for s in v2_script.SEGMENTS:
        text = spoken(s["vo"]); wav = os.path.join(VO, f"{s['id']}.wav")
        h = hashlib.sha1(f"{a.engine}|{a.voice}|{a.rate}|{text}".encode()).hexdigest()[:12]
        if not a.force and old.get(s["id"], {}).get("hash") == h and os.path.exists(wav):
            out[s["id"]] = dict(old[s["id"]], seg_s=round(max(s["nominal"], v2_script.VO_LEAD + old[s["id"]]["vo_s"]
                                                              + v2_script.VO_PAD), 3))
            print(s["id"], "cached", out[s["id"]]["vo_s"]); continue
        eng = a.engine
        try:
            tts(eng, text, wav, a.voice, a.rate)
        except Exception as e:  # network down etc.
            print(s["id"], f"{eng} failed ({e.__class__.__name__}); falling back to piper", file=sys.stderr)
            eng = "piper"; tts(eng, text, wav, a.voice, a.rate)
        d = dur(wav)
        seg = max(s["nominal"], v2_script.VO_LEAD + d + v2_script.VO_PAD)
        out[s["id"]] = dict(vo_s=round(d, 3), seg_s=round(seg, 3), engine=eng,
                            voice=a.voice if eng == "edge" else os.path.basename(PV),
                            hash=h if eng == a.engine else "fallback")  # a fallback is retried next run
        print(s["id"], eng, f"vo {d:.1f}s  seg {seg:.1f}s", flush=True)
    tot = sum(v["seg_s"] for v in out.values())
    print(f"total {tot:.1f} s (cap {v2_script.MAX_TOTAL})")
    json.dump(out, open(dj, "w"), indent=1)
    if tot > v2_script.MAX_TOTAL:
        sys.exit(f"TOO LONG: {tot:.1f} s > {v2_script.MAX_TOTAL} s; shorten text in demo/{_SCRIPT}_script.py")
