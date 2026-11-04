#!/bin/bash
# One command to (re)build demo video v2: narration (cached per segment) -> script doc -> render -> mux.
#   bash demo/render_v2.sh            # full render (~15-25 min with 3 workers while experiments run)
#   bash demo/render_v2.sh s6         # only re-render the repair segment (after data/gated results land)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 demo/make_vo.py
python3 demo/v2_script.py
nice -n 10 python3 demo/make_video_v2.py "$@"
