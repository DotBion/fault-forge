#!/bin/bash
# Record N real takes of `make live`:  bash demo/record_live.sh [N]   -> demo/live/take<k>.cast (+ .gif via agg)
# asciinema records in real time (no idle-time limit); speed-ups are applied only in the video, with a burned-in label.
set -e
cd "$(dirname "$0")/.."
N=${1:-2}; AS=${ASCIINEMA:-asciinema}
for k in $(seq 1 "$N"); do
  "$AS" rec -q --overwrite --cols 150 --rows 44 -c "bash demo/live_take.sh" "demo/live/take$k.cast"
done
