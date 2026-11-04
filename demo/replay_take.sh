#!/bin/bash
# Real terminal take of `make replay` (keyless): asciinema rec -c "bash demo/replay_take.sh" demo/live/replay.cast
cd "$(dirname "$0")/.."
unset NO_COLOR
printf '\033[1;32m$\033[0m make replay\n'
make replay
