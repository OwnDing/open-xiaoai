#!/bin/zsh
# Half-res look-dev stills at chosen plate times, then a contact sheet.
#   scripts/lookdev.sh "P01:1,6,8.5" "P06:3,13" ...
cd "${0:A:h}/.."
B=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
mkdir -p build/logs build/lookdev
for spec in $@; do
  p=${spec%%:*}; times=(${(s:,:)${spec#*:}})
  args=()
  for t in $times; do args+=(--still $t); done
  $B -b --factory-startup -P src/blender/render_plate.py -- $p $args --res ${RES:-0.5} --samples ${SAMPLES:-16} --blur 0 > build/logs/lookdev_$p.log 2>&1 || { echo "$p FAILED"; grep -A12 Traceback build/logs/lookdev_$p.log | head -30; }
done
.venv/bin/python src/contact_sheet.py build/lookdev ${SHEET:-build/lookdev_sheet.jpg} $@
