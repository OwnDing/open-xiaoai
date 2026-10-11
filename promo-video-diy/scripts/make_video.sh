#!/bin/zsh
# Build the finished film from the rendered plates:
#   voices (if missing) -> timeline -> soundtrack -> compositor -> final encode.
set -e
cd "${0:A:h}/.."
PY=$PWD/.venv/bin/python
[[ -f build/audio/voice/meta.json ]] || $PY src/tts.py
[[ -f build/textures/worksheet.png ]] || $PY src/textures.py
$PY src/timeline.py > /dev/null
(cd src/audio && $PY mix.py)
(cd src/compositor && node render.mjs --out ../../build/video.mp4 $@)
mkdir -p output
ffmpeg -y -v error -stats -i build/video.mp4 -i build/audio/mix.wav \
  -filter_complex "[0:v]noise=alls=2:allf=t,format=yuv420p[v];[1:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 19 -maxrate 9M -bufsize 18M -tune film -profile:v high \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 \
  -c:a aac -b:a 256k -movflags +faststart -metadata title="家的大脑 · Open-XiaoAI" \
  output/home-brain.mp4
$PY src/storyboard_sheet.py output/home-brain.mp4 output/storyboard_frames.jpg
# Cover: the title over the floating home.
CF=$($PY src/frames_at.py S03:title+2.4)
ffmpeg -y -v error -ss $(echo "$CF / 24" | bc -l) -i output/home-brain.mp4 -frames:v 1 -q:v 2 output/cover.jpg
echo "done: output/home-brain.mp4"
