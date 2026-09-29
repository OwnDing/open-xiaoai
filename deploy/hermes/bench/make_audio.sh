#!/bin/sh
# Synthesize the test utterances as 16 kHz mono s16le PCM (macOS `say` + ffmpeg).
set -e
cd "$(dirname "$0")"
mkdir -p audio
while IFS="$(printf '\t')" read -r id text; do
  say -v Tingting -o "audio/$id.aiff" "$text"
  ffmpeg -loglevel error -y -i "audio/$id.aiff" -ar 16000 -ac 1 -f s16le "audio/$id.pcm"
  rm "audio/$id.aiff"
done < utterances.tsv
