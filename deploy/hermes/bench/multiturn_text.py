"""Multi-turn text conversation through xiaozhi-esp32-server on one connection.

Unlike voice_bench.py (one connection per question), the server keeps the
dialogue history here, which is what makes a model copy its earlier replies.

    python multiturn_text.py "关闭书房灯，打开次卧灯" "关闭次卧灯，打开书房灯" --rounds 4
"""

import argparse
import asyncio
import json
import time
import uuid

import websockets


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phrases", nargs="+")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--url", default="ws://host.docker.internal:18000/xiaozhi/v1/")
    parser.add_argument("--pause", type=float, default=3.0)
    args = parser.parse_args()

    headers = {
        "Authorization": "Bearer bench",
        "Protocol-Version": "1",
        "Device-Id": "be:nc:h0:00:00:02",
        "Client-Id": str(uuid.uuid4()),
    }
    async with websockets.connect(args.url, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "hello", "version": 1, "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
        }))
        while True:
            message = json.loads(await ws.recv())
            if message.get("type") == "hello":
                session_id = message.get("session_id", "")
                break
        await asyncio.sleep(2)
        for round_index in range(args.rounds):
            for phrase in args.phrases:
                t0 = time.perf_counter()
                await ws.send(json.dumps({"session_id": session_id, "type": "listen", "state": "detect", "text": phrase}))
                sentences, first_s = [], None
                while True:
                    message = await asyncio.wait_for(ws.recv(), 90)
                    if isinstance(message, bytes):
                        continue
                    data = json.loads(message)
                    if data.get("type") == "tts" and data.get("state") == "sentence_start":
                        if first_s is None:
                            first_s = round(time.perf_counter() - t0, 2)
                        sentences.append(data.get("text", ""))
                    if data.get("type") == "tts" and data.get("state") == "stop":
                        break
                print(f"r{round_index} {phrase} | first={first_s}s | {''.join(sentences)}", flush=True)
                await asyncio.sleep(args.pause)


if __name__ == "__main__":
    asyncio.run(main())
