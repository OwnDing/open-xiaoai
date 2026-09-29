#!/bin/sh
# Voice benchmark rounds with the demo HA reset before each round.
# usage: ab_voice.sh <label> <rounds> [cases]
set -e
PY=/app/.venv/bin/python
LABEL=$1; ROUNDS=$2; CASES=${3:-c1,c2,c3,c4,c5,h1,w1,m1,m2}
i=0
while [ $i -lt "$ROUNDS" ]; do
  $PY ha_ctl.py reset > /dev/null
  $PY voice_bench.py --label "$LABEL" --cases "$CASES" --repeat 1 --out "${LABEL}_voice.jsonl"
  i=$((i+1))
done
