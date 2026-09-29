#!/bin/sh
# Device-control latency: reset HA, speak "把客厅灯关掉", read when the light changed.
# usage: ha_case.sh <label> <rounds>
set -e
PY=/app/.venv/bin/python
i=0
while [ $i -lt "$2" ]; do
  $PY ha_ctl.py reset > /dev/null
  sleep 2
  $PY voice_bench.py --label "$1" --cases h1 --repeat 1 --out "$1_ha.jsonl"
  $PY ha_ctl.py show | grep ke_ting_deng >> "$1_ha_states.txt"
  i=$((i+1))
done
