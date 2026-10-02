#!/bin/zsh
# Render every Blender plate (or the ones given as arguments).
# Frames that already exist are skipped, so the script can be re-run to resume.
cd "${0:A:h}/.."
B=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
mkdir -p build/logs
if (( $# )); then plates=($@); else plates=(P01 P02 P03 P04 P05 P12 P13 P08 P10 P06 P07 P07B P09 P11); fi
for p in $plates; do
  echo "$(date +%T) $p start"
  $B -b --factory-startup -P src/blender/render_plate.py -- $p > build/logs/$p.log 2>&1 || echo "$p FAILED (see build/logs/$p.log)"
  echo "$(date +%T) $p done: $(ls build/plates/$p/*.jpg 2>/dev/null | wc -l | tr -d ' ') frames"
done
