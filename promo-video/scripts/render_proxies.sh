#!/bin/zsh
# Quarter-resolution, low-sample stand-ins for every plate, for compositor work.
cd "${0:A:h}/.."
B=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
mkdir -p build/logs
if (( $# )); then plates=($@); else plates=(P05 P12 P13 P08 P10 P06 P07 P07B P09 P11 P03 P04); fi
for p in $plates; do
  $B -b --factory-startup -P src/blender/render_plate.py -- $p --res 0.25 --samples 6 --step 3 --out build/proxy/$p > build/logs/proxy_$p.log 2>&1 || echo "$p FAILED"
  echo "$(date +%T) proxy $p: $(ls build/proxy/$p/*.jpg 2>/dev/null | wc -l | tr -d ' ') frames"
done
