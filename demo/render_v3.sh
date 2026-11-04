#!/bin/bash
# One command for demo video v3:  bash demo/render_v3.sh [segment ids...]
# narration (cached by text hash) -> docs/video_v3_script.md -> segments -> mux -> demo/faultforge_demo_v3.mp4
# Gate numbers and the trend chart are re-read from data/gated/ and plots/ on every run.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}; [ -x /workspace/ttsvenv/bin/python3 ] && TTS_PY=${TTS_PY:-/workspace/ttsvenv/bin/python3} || TTS_PY=${TTS_PY:-$PY}
"$TTS_PY" demo/make_vo.py --script v3
"$PY" demo/v3_script.py
FF_RENDER_WORKERS=${FF_RENDER_WORKERS:-2} nice -n 10 "$PY" demo/make_video_v3.py "$@"
