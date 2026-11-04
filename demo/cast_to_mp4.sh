#!/bin/bash
# Render asciinema casts to constant-frame-rate mp4 in REAL time (agg's default 5 s idle limit is disabled):
#   bash demo/cast_to_mp4.sh demo/live/take1.cast [more.cast ...]   -> demo/live/take1.mp4 ...
set -e
for c in "$@"; do
  g="${c%.cast}.gif"; m="${c%.cast}.mp4"
  agg --idle-time-limit 1000 --last-frame-duration 3 --font-family "DejaVu Sans Mono" "$c" "$g"
  ffmpeg -y -loglevel error -i "$g" -vf "fps=30,pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p" -c:v libx264 -crf 18 \
    -movflags +faststart "$m"
  rm -f "$g"
  echo "$m $(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$m") s"
done
