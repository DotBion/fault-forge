#!/bin/bash
# One real, unedited terminal take of `make live` (recorded by demo/record_live.sh with asciinema).
cd "$(dirname "$0")/.."
unset NO_COLOR
printf '\033[1;32m$\033[0m date -u; make live\n'
date -u
make live LIVE_ARGS="${LIVE_ARGS:---workers 4}"
