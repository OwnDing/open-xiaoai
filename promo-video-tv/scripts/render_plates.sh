#!/bin/zsh
# Render every Blender plate (or the ones given as arguments).
# Frames that already exist are skipped, so the script can be re-run to resume.
# A crashed frame leaves an empty placeholder, which is removed before each retry.
cd "${0:A:h}/.."
B=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
mkdir -p build/logs
if (( $# )); then plates=($@); else plates=(P01 P04 P05 P06 P09 P10 P13 P14 P15 P16 P17 P18); fi
total() { .venv/bin/python -c "import json,sys; p=json.load(open('build/timeline.json'))['plates'][sys.argv[1]]; print(p['frames']+24)" $1; }
for p in $plates; do
  echo "$(date +%T) $p start"
  want=$(total $p)
  for try in 1 2 3 4 5 6; do
    find build/plates/$p -name "*.jpg" -size 0 -delete 2>/dev/null
    $B -b --factory-startup -P src/blender/render_plate.py -- $p > build/logs/$p.log 2>&1
    have=$(ls build/plates/$p/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    (( have >= want )) && break
    echo "$(date +%T) $p crashed at $have/$want frames, retry $try"
  done
  find build/plates/$p -name "*.jpg" -size 0 -delete 2>/dev/null
  have=$(ls build/plates/$p/*.jpg 2>/dev/null | wc -l | tr -d ' ')
  (( have >= want )) && echo "$(date +%T) $p done: $have frames" || echo "$(date +%T) $p FAILED: $have/$want frames"
  grep -c "Shadow buffer full" build/logs/$p.log | sed "s/^/  shadow-buffer warnings: /"
done
