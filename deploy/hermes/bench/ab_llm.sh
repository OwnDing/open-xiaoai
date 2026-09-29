#!/bin/sh
# Interleave direct DeepSeek and Hermes so both see the same API conditions.
set -e
PY=/app/.venv/bin/python
for round in 1 2 3 4; do
  $PY llm_bench.py --label direct --base-url https://api.deepseek.com --model deepseek-flash \
      --api-key-env DEEPSEEK_API_KEY --disable-thinking --cases c1,c2,c3,c4,c5 --repeat 1 --out ab_llm.jsonl
  $PY llm_bench.py --label hermes --base-url http://hermes:8642/v1 --model xiaoqi-home \
      --api-key-env API_SERVER_KEY --cases c1,c2,c3,c4,c5 --repeat 1 --out ab_llm.jsonl
done
