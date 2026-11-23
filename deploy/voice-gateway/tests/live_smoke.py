"""Live smoke test against a running voice-gateway (read-only queries only).

Run inside the voice-gateway container:
    python /app/tests/live_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

import numpy as np
import opuslib_next as opuslib
import websockets

URL = os.getenv("SMOKE_WS_URL", "ws://127.0.0.1:8000/xiaozhi/v1/")
SHERPA_URL = os.getenv("SMOKE_SHERPA_URL", "http://sherpa-tts:11996/tts")


async def connect(device_id: str):
    headers = {
        "Authorization": "Bearer smoke",
        "Protocol-Version": "1",
        "Device-Id": device_id,
        "Client-Id": f"smoke-{device_id}",
    }
    ws = await websockets.connect(URL, additional_headers=headers, max_size=None)
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "version": 1,
                "transport": "websocket",
                "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
            }
        )
    )
    hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
    assert hello["type"] == "hello" and hello["session_id"], hello
    return ws, hello["session_id"]


async def ask_text(device_id: str, text: str) -> dict:
    t0 = time.perf_counter()
    ws, sid = await connect(device_id)
    try:
        await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "detect", "text": text}))
        sents, pkts, first_s, first_a = [], [], None, None
        while True:
            msg = await asyncio.wait_for(ws.recv(), 60)
            dt = round(time.perf_counter() - t0, 2)
            if isinstance(msg, bytes):
                if first_a is None:
                    first_a = dt
                pkts.append(msg)
                continue
            d = json.loads(msg)
            if d.get("type") == "tts" and d.get("state") == "sentence_start":
                if first_s is None:
                    first_s = dt
                sents.append(d.get("text", ""))
            elif d.get("type") == "tts" and d.get("state") == "stop":
                break
        # Verify server Opus frames actually decode to non-silent PCM.
        decoded_rms = 0.0
        if pkts:
            dec = opuslib.Decoder(24000, 1)
            pcm = b"".join(dec.decode(p, 1440) for p in pkts)
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
            decoded_rms = round(float(np.sqrt(np.mean(samples**2) + 1e-12)), 1)
        return {
            "sents": "".join(sents),
            "pkts": len(pkts),
            "rms": decoded_rms,
            "first_s": first_s,
            "first_a": first_a,
            "total": round(time.perf_counter() - t0, 2),
        }
    finally:
        await ws.close()


async def ask_real_audio(device_id: str, spoken_text: str) -> dict:
    req = urllib.request.Request(
        SHERPA_URL,
        data=json.dumps({"text": spoken_text, "character": "xiao_ya"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    pcm24 = urllib.request.urlopen(req, timeout=15).read()
    s24 = np.frombuffer(pcm24[: len(pcm24) // 2 * 2], dtype="<i2").astype(np.float32)
    idx = np.linspace(0, len(s24) - 1, int(len(s24) * 16000 / 24000))
    s16 = np.interp(idx, np.arange(len(s24)), s24).astype("<i2").tobytes()
    s16 += b"\x00\x00" * 4800  # 300 ms trailing silence
    enc = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
    frames = []
    for off in range(0, len(s16), 1920):
        chunk = s16[off : off + 1920].ljust(1920, b"\x00")
        frames.append(enc.encode(chunk, 960))

    ws, sid = await connect(device_id)
    try:
        await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "start", "mode": "manual"}))
        for frame in frames:
            await ws.send(frame)
        t0 = time.perf_counter()
        await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "stop"}))
        stt, stt_s, sents, pkts = None, None, [], 0
        while True:
            msg = await asyncio.wait_for(ws.recv(), 60)
            dt = round(time.perf_counter() - t0, 2)
            if isinstance(msg, bytes):
                pkts += 1
                continue
            d = json.loads(msg)
            if d.get("type") == "stt":
                stt, stt_s = d.get("text"), dt
            elif d.get("type") == "tts" and d.get("state") == "sentence_start":
                sents.append(d.get("text", ""))
            elif d.get("type") == "tts" and d.get("state") == "stop":
                break
        return {
            "stt": stt,
            "stt_s": stt_s,
            "sents": "".join(sents),
            "pkts": pkts,
            "total": round(time.perf_counter() - t0, 2),
        }
    finally:
        await ws.close()


async def main() -> None:
    r1 = await ask_text("02:76:74:00:00:fe", "一加一等于几？只回答结果。")
    print("1. native_xiaomi text-only:", r1, flush=True)
    assert r1["pkts"] == 0 and ("2" in r1["sents"] or "二" in r1["sents"]), r1

    r2 = await ask_text("02:76:74:00:00:01", "我现在在哪个房间？如果系统没有告诉你，就只回答不知道。")
    print("2. EdgeStreamTTS + room(书房):", r2, flush=True)
    assert r2["pkts"] >= 5 and r2["rms"] > 200 and "书房" in r2["sents"], r2

    r3 = await ask_text("02:76:74:00:00:02", "一加一等于几？")
    print("3. EdgeTTS + room(卧室):", r3, flush=True)
    assert r3["pkts"] >= 5 and r3["rms"] > 200 and ("2" in r3["sents"] or "二" in r3["sents"]), r3

    r4 = await ask_real_audio("02:76:74:00:00:fe", "冰箱冷冻室现在几度")
    print("4. REAL AUDIO -> ASR + Voiceprint + HA state:", r4, flush=True)
    assert r4["stt"] and r4["sents"] and r4["pkts"] == 0, r4

    c1, c2 = await asyncio.gather(
        ask_text("02:76:74:00:00:01", "二加三等于几？"),
        ask_text("02:76:74:00:00:fe", "三加四等于几？"),
    )
    print("5. Concurrent 2 devices:", c1, "|", c2, flush=True)
    assert ("5" in c1["sents"] or "五" in c1["sents"]) and c1["pkts"] >= 3 and c1["rms"] > 200
    assert ("7" in c2["sents"] or "七" in c2["sents"]) and c2["pkts"] == 0
    print("ALL 5 LIVE STAGING E2E CHECKS PASSED!", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
