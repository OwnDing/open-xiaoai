"""Streaming latency benchmark for OpenAI-compatible chat endpoints.

Measures, per request:
  ttft_s            first non-empty `delta.content`
  first_sentence_s  first chunk that completes a sentence the way
                    xiaozhi-esp32-server segments text for TTS
  total_s           end of stream
  tool_events       Hermes `hermes.tool.progress` events seen in the stream

Example (inside any image with `requests`):
    python llm_bench.py --label deepseek --base-url https://api.deepseek.com \
        --model deepseek-flash --api-key-env DEEPSEEK_API_KEY --disable-thinking
    python llm_bench.py --label hermes --base-url http://hermes:8642/v1 \
        --model xiaoqi-home --api-key-env API_SERVER_KEY
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests

SYSTEM_PROMPT = "你是家庭语音助手小七。请使用简洁、自然的中文回答，除非用户要求详细说明。"
SENTENCE_MARKS = set("。？！；：.?!;:，,、\n")


def load_utterances(path):
    utterances = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            case_id, text = line.split("\t", 1)
            utterances[case_id] = text
    return utterances


def run_one(args, api_key, question):
    body = {
        "model": args.model,
        "stream": True,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    }
    if args.disable_thinking:
        body["thinking"] = {"type": "disabled"}
    headers = {"Authorization": f"Bearer {api_key}"}
    if args.session_id:
        headers["X-Hermes-Session-Id"] = args.session_id

    url = args.base_url.rstrip("/") + "/chat/completions"
    result = {"label": args.label, "question": question}
    t0 = time.perf_counter()
    text = ""
    tool_events = []
    event_name = None
    with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
        result["status"] = resp.status_code
        result["headers_s"] = round(time.perf_counter() - t0, 3)
        if resp.status_code != 200:
            result["error"] = resp.text[:500]
            return result
        for raw in resp.iter_lines(decode_unicode=True):
            now = round(time.perf_counter() - t0, 3)
            if raw is None or raw == "" or raw.startswith(":"):
                event_name = None if raw == "" else event_name
                continue
            if raw.startswith("event:"):
                event_name = raw[6:].strip()
                continue
            if not raw.startswith("data:"):
                continue
            payload = raw[5:].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event_name and event_name != "message":
                tool_events.append({"t": now, "event": event_name, "data": data})
                continue
            choices = data.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content"):
                result.setdefault("first_reasoning_s", now)
            content = delta.get("content") or ""
            if content:
                result.setdefault("ttft_s", now)
                text += content
                if "first_sentence_s" not in result and any(
                    mark in content for mark in SENTENCE_MARKS
                ):
                    result["first_sentence_s"] = now
    result["total_s"] = round(time.perf_counter() - t0, 3)
    result["answer"] = text
    result["chars"] = len(text)
    if tool_events:
        result["tool_events"] = [
            {"t": event["t"], "tool": event["data"].get("tool") or event["data"].get("name")}
            for event in tool_events
        ]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument("--cases", default="c1,c2,c3,c4,c5")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--utterances", default="utterances.tsv")
    parser.add_argument("--out", default="llm_results.jsonl")
    args = parser.parse_args()

    api_key = os.environ[args.api_key_env]
    utterances = load_utterances(args.utterances)
    cases = [case.strip() for case in args.cases.split(",") if case.strip()]
    with open(args.out, "a", encoding="utf-8") as out:
        for round_index in range(args.repeat):
            for case_id in cases:
                try:
                    result = run_one(args, api_key, utterances[case_id])
                except Exception as error:
                    result = {"label": args.label, "error": repr(error)}
                result.update(
                    case=case_id,
                    round=round_index,
                    ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
                out.flush()
                print(
                    f"[{args.label}] {case_id} r{round_index} "
                    f"ttft={result.get('ttft_s')} sent={result.get('first_sentence_s')} "
                    f"total={result.get('total_s')} tools={len(result.get('tool_events', []))} "
                    f"err={str(result.get('error', ''))[:80]} | {result.get('answer', '')[:30]}",
                    flush=True,
                )
                time.sleep(args.pause)


if __name__ == "__main__":
    main()
