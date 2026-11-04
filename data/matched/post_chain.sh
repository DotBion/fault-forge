#!/bin/bash
# waits for run_matched_chain.sh (matched_compare) to finish, then report + v4 s4/s5 re-render. Safe to re-run.
cd /workspace/faultforge
while pgrep -f run_matched_chain.sh >/dev/null || pgrep -f matched_compare.py >/dev/null; do sleep 60; done
grep -q CHAIN_DONE data/matched/chain.log || { echo "chain did not finish cleanly"; exit 1; }
[ -f data/matched/summary.json ] || { echo "no summary.json"; exit 1; }
python3 src/matched_report.py || exit 1
echo REPORT_DONE
TTS_PY=python3; [ -x /workspace/ttsvenv/bin/python3 ] && TTS_PY=/workspace/ttsvenv/bin/python3
"$TTS_PY" demo/make_vo.py --script v4 || exit 1
python3 -c "import json,sys; d=json.load(open('demo/vo_v4/durations.json')); sys.exit(0 if all(v['engine']=='edge' for v in d.values()) else 'VO fell back to piper; not rendering')" || exit 1
python3 demo/v4_script.py || exit 1
FF_RENDER_WORKERS=2 nice -n 10 python3 demo/make_video_v4.py s4 s5 || exit 1
ffprobe -v error -show_entries format=duration -of csv=p=0 demo/faultforge_demo_v4.mp4
echo POST_DONE
