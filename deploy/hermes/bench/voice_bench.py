"""Fake Xiaozhi device used to measure backend voice latency.

The script talks to xiaozhi-esp32-server exactly like the Open-XiaoAI bridge
does: hello -> listen start (manual) -> real-time Opus frames -> listen stop.
All timings are measured from the moment `listen stop` is sent, which is the
moment the bridge's VAD decides the user has finished speaking.

Run it inside the bridge image so opuslib/websockets are available:

    docker run --rm -v %CD%:/bench -w /bench \
        --entrypoint /app/.venv/bin/python \
        local/open-xiaoai-xiaozhi:smooth-audio \
        voice_bench.py --label deepseek --cases c1,c2 --repeat 3
"""

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import opuslib_next as opuslib
import websockets

SAMPLE_RATE = 16000
FRAME_MS = 60
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


def load_utterances(path):
    utterances = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            case_id, text = line.split("\t", 1)
            utterances[case_id] = text
    return utterances


def encode_pcm(pcm_path):
    encoder = opuslib.Encoder(SAMPLE_RATE, 1, opuslib.APPLICATION_VOIP)
    pcm = Path(pcm_path).read_bytes()
    # 300 ms of trailing silence, like a user pausing before the VAD fires.
    pcm += b"\x00\x00" * (SAMPLE_RATE * 3 // 10)
    frame_bytes = FRAME_SAMPLES * 2
    frames = []
    for offset in range(0, len(pcm), frame_bytes):
        chunk = pcm[offset : offset + frame_bytes]
        if len(chunk) < frame_bytes:
            chunk += b"\x00" * (frame_bytes - len(chunk))
        frames.append(encoder.encode(chunk, FRAME_SAMPLES))
    return frames


async def run_case(args, case_id, text, frames, device_id):
    headers = {
        "Authorization": "Bearer bench",
        "Protocol-Version": "1",
        "Device-Id": device_id,
        "Client-Id": str(uuid.uuid4()),
    }
    result = {
        "label": args.label,
        "case": case_id,
        "question": text,
        "mode": "text" if args.text_mode else "audio",
    }
    async with websockets.connect(
        args.url, additional_headers=headers, max_size=None
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "version": 1,
                    "transport": "websocket",
                    "audio_params": {
                        "format": "opus",
                        "sample_rate": 16000,
                        "channels": 1,
                        "frame_duration": 60,
                    },
                }
            )
        )
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if message.get("type") == "hello":
                session_id = message.get("session_id", "")
                break
        # Let the server finish its asynchronous prompt/component setup.
        await asyncio.sleep(args.settle)

        if args.text_mode:
            t0 = time.perf_counter()
            result["t0_wall"] = time.time()
            await ws.send(
                json.dumps(
                    {
                        "session_id": session_id,
                        "type": "listen",
                        "state": "detect",
                        "text": text,
                    }
                )
            )
        else:
            await ws.send(
                json.dumps(
                    {
                        "session_id": session_id,
                        "type": "listen",
                        "state": "start",
                        "mode": "manual",
                    }
                )
            )
            started = time.perf_counter()
            for index, frame in enumerate(frames):
                await ws.send(frame)
                delay = started + (index + 1) * FRAME_MS / 1000 - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
            await ws.send(
                json.dumps(
                    {"session_id": session_id, "type": "listen", "state": "stop"}
                )
            )
            t0 = time.perf_counter()
            result["t0_wall"] = time.time()

        sentences = []
        deadline = t0 + args.timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                result["error"] = "timeout"
                break
            try:
                message = await asyncio.wait_for(ws.recv(), remaining)
            except asyncio.TimeoutError:
                result["error"] = "timeout"
                break
            now = time.perf_counter() - t0
            if isinstance(message, bytes):
                result.setdefault("first_audio_s", round(now, 3))
                continue
            data = json.loads(message)
            kind = data.get("type")
            state = data.get("state")
            if kind == "stt":
                result.setdefault("stt_s", round(now, 3))
                result.setdefault("stt_text", data.get("text"))
            elif kind == "tts" and state == "start":
                result.setdefault("tts_start_s", round(now, 3))
            elif kind == "tts" and state == "sentence_start":
                sentences.append((round(now, 3), data.get("text", "")))
            elif kind == "tts" and state == "stop":
                result["tts_stop_s"] = round(now, 3)
                break

        if sentences:
            result["first_sentence_s"] = sentences[0][0]
            result["first_sentence"] = sentences[0][1]
            result["last_sentence_s"] = sentences[-1][0]
            result["sentences"] = sentences
        result["answer"] = "".join(text for _, text in sentences)
        try:
            await ws.send(json.dumps({"session_id": session_id, "type": "abort"}))
        except Exception:
            pass
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://host.docker.internal:18000/xiaozhi/v1/")
    parser.add_argument("--label", required=True)
    parser.add_argument("--cases", default="c1,c2,c3,c4,c5")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--settle", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--text-mode", action="store_true")
    parser.add_argument("--audio-dir", default="audio")
    parser.add_argument("--utterances", default="utterances.tsv")
    parser.add_argument("--device-id", default="be:nc:h0:00:00:01")
    parser.add_argument("--out", default="results.jsonl")
    args = parser.parse_args()

    utterances = load_utterances(args.utterances)
    cases = [case.strip() for case in args.cases.split(",") if case.strip()]
    with open(args.out, "a", encoding="utf-8") as out:
        for round_index in range(args.repeat):
            for case_id in cases:
                frames = (
                    []
                    if args.text_mode
                    else encode_pcm(Path(args.audio_dir) / f"{case_id}.pcm")
                )
                try:
                    result = await run_case(
                        args, case_id, utterances[case_id], frames, args.device_id
                    )
                except Exception as error:
                    result = {
                        "label": args.label,
                        "case": case_id,
                        "error": repr(error),
                    }
                result["round"] = round_index
                result["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
                out.flush()
                print(
                    f"[{args.label}] {case_id} r{round_index} "
                    f"stt={result.get('stt_s')} first={result.get('first_sentence_s')} "
                    f"stop={result.get('tts_stop_s')} err={result.get('error')} "
                    f"| {result.get('first_sentence', '')[:30]}",
                    flush=True,
                )
                await asyncio.sleep(args.pause)


if __name__ == "__main__":
    asyncio.run(main())
