"""Backend routing checks against a running xiaozhi backend.

  VT_BACKEND_URL=ws://127.0.0.1:18100/xiaozhi/v1/ pytest -m backend

VT_AUDIO_DEVICE must be listed in the backend's XIAOZHI_SERVER_AUDIO_DEVICES;
VT_TEXT_DEVICE must not be (it stands in for the 小爱 bridge).
"""

import asyncio
import json
import os

import pytest
import websockets

URL = os.environ.get("VT_BACKEND_URL", "")
AUDIO_DEVICE = os.environ.get("VT_AUDIO_DEVICE", "02:76:74:00:00:02")
TEXT_DEVICE = os.environ.get("VT_TEXT_DEVICE", "02:76:74:00:00:fe")
QUESTION = "一加一等于几？只回答结果。"
# A one-word answer ("二") is about 7 packets of 60 ms.
MIN_AUDIO_PACKETS = 3

pytestmark = [pytest.mark.backend, pytest.mark.skipif(not URL, reason="VT_BACKEND_URL not set")]


async def ask(device_id: str, text: str, timeout: float = 60.0) -> dict:
    headers = {"Authorization": "Bearer ", "Protocol-Version": "1", "Device-Id": device_id, "Client-Id": f"test-{device_id}"}
    result = {"stt": None, "sentences": [], "audio_packets": 0, "audio_bytes": 0, "stopped": False}
    async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                  "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}))
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert hello["type"] == "hello"
        await ws.send(json.dumps({"session_id": hello.get("session_id", ""), "type": "listen", "state": "detect", "text": text}))
        async with asyncio.timeout(timeout):
            async for message in ws:
                if isinstance(message, bytes):
                    result["audio_packets"] += 1
                    result["audio_bytes"] += len(message)
                    continue
                data = json.loads(message)
                if data.get("type") == "stt":
                    result["stt"] = data.get("text")
                elif data.get("type") == "tts" and data.get("state") == "sentence_start":
                    result["sentences"].append(data.get("text", ""))
                elif data.get("type") == "tts" and data.get("state") == "stop":
                    result["stopped"] = True
                    break
        # Audio may trail the stop message slightly.
        try:
            while True:
                message = await asyncio.wait_for(ws.recv(), 1.0)
                if isinstance(message, bytes):
                    result["audio_packets"] += 1
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
    return result


def test_listed_device_gets_server_audio():
    result = asyncio.run(ask(AUDIO_DEVICE, QUESTION))
    assert result["stopped"] and result["sentences"], result
    assert "2" in "".join(result["sentences"]) or "二" in "".join(result["sentences"]), result
    assert result["audio_packets"] >= MIN_AUDIO_PACKETS, result


def test_unlisted_device_gets_text_only():
    result = asyncio.run(ask(TEXT_DEVICE, QUESTION))
    assert result["stopped"] and result["sentences"], result
    assert result["audio_packets"] == 0, result


def test_two_devices_at_once_get_their_own_answers():
    async def both():
        return await asyncio.gather(
            ask(AUDIO_DEVICE, "一加一等于几？只回答结果。"),
            ask(TEXT_DEVICE, "三加四等于几？只回答结果。"),
        )

    audio, text = asyncio.run(both())
    audio_reply, text_reply = "".join(audio["sentences"]), "".join(text["sentences"])
    assert ("2" in audio_reply or "二" in audio_reply) and "7" not in audio_reply, audio
    assert ("7" in text_reply or "七" in text_reply) and "2" not in text_reply, text
    assert audio["audio_packets"] >= MIN_AUDIO_PACKETS and text["audio_packets"] == 0
