"""Unit and WebSocket protocol integration tests for voice-gateway."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import websockets

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gateway.config import GatewayConfig
from gateway.health import AudioHealthSink, sanitize
from gateway.llm import LLMBridge
from gateway.main import VoiceGatewayApp
from gateway.opus import ContinuousOpusEncoder24k, OpusDecoder16k, pcm16_to_wav
from gateway.text import SentenceSplitter, clean_markdown
from gateway.tts import DeviceTTSPipeline, SilenceTrimmer


class FakeASR:
    def __init__(self, transcript: str = "客厅灯开着吗？"):
        self.transcript = transcript
        self.model_path = Path("fake.onnx")
        self.utterances = 0
        self.total_infer_s = 0.0
        self.calls: list[tuple[int, int]] = []

    async def transcribe_pcm16(self, pcm: bytes, sample_rate: int = 16000) -> tuple[str, float]:
        self.utterances += 1
        self.calls.append((len(pcm), sample_rate))
        return self.transcript, 0.05


class FakeLLMProvider:
    def __init__(self, chunks_fn=None):
        self.chunks_fn = chunks_fn or (lambda sid, dialogue: ["客厅灯", "现在是开着的。", "需要我帮您关掉吗？"])
        self.calls: list[tuple[str, list[dict]]] = []

    def response(self, session_id: str, dialogue: list[dict], **_kwargs):
        self.calls.append((session_id, dialogue))
        for item in self.chunks_fn(session_id, dialogue):
            yield item


class FakePCMBackend:
    def __init__(self, fail: bool = False, tag: str = "fake"):
        self.fail = fail
        self.tag = tag
        self.texts: list[str] = []

    async def stream_pcm(self, text: str, abort_event: asyncio.Event):
        self.texts.append(text)
        if self.fail:
            raise RuntimeError(f"{self.tag} failed")
        # 180 ms of 24 kHz sine wave (3 full 60 ms Opus frames).
        t = np.arange(24000 * 180 // 1000, dtype=np.float32) / 24000.0
        pcm = (np.sin(2 * np.pi * 440.0 * t) * 8000.0).astype("<i2").tobytes()
        if not abort_event.is_set():
            yield pcm

    async def close(self) -> None:
        return


class TestTextAndConfig(unittest.TestCase):
    def test_clean_markdown_strips_markup_and_emoji(self):
        cleaned = clean_markdown("**你好**，`客厅灯` 已打开 😊 [详情](https://example.com)")
        self.assertEqual(cleaned, "你好，客厅灯 已打开 详情")

    def test_sentence_splitter_fast_first_cut_and_decimal_protection(self):
        sp = SentenceSplitter()
        out = []
        for token in ["空调", "现在", "是26", ".5度，", "室外", "天气很好。", "记得添衣"]:
            out.extend(sp.feed(token))
        out.extend(sp.flush())
        self.assertEqual(out, ["空调现在是26.5度，", "室外天气很好。", "记得添衣"])

    def test_sentence_splitter_time_protection(self):
        sp = SentenceSplitter()
        out = sp.feed("现在是11:30，准备出发。") + sp.flush()
        self.assertEqual(out, ["现在是11:30，", "准备出发。"])

    def test_config_reads_xiaozhi_format(self):
        raw = {
            "selected_module": {"ASR": "SherpaASR", "LLM": "HermesAgentLLM", "TTS": "SherpaOnnxTTS"},
            "ASR": {"SherpaASR": {"type": "sherpa_onnx_local", "model_dir": "models/sherpa-onnx-sense-voice"}},
            "TTS": {"EdgeStreamTTS": {"type": "edge_stream", "voice": "zh-CN-XiaoxiaoNeural"}},
            "voice_devices": {
                "02:76:74:00:00:01": {
                    "output": "server_audio",
                    "tts": "EdgeStreamTTS",
                    "room": "书房",
                    "reply_style": "sentence",
                    "send_interval_ms": 50,
                },
                "02:76:74:00:00:02": {
                    "output": "server_audio",
                    "tts": "EdgeTTS",
                    "room": "卧室",
                },
            },
        }
        cfg = GatewayConfig(raw, base_dir=Path("/tmp/gw"))
        self.assertFalse(cfg.wants_server_audio("aa:bb:cc:dd:ee:ff"))
        self.assertTrue(cfg.wants_server_audio("02:76:74:00:00:01"))
        p1 = cfg.device_profile("02:76:74:00:00:01")
        self.assertEqual(p1.tts_name, "EdgeStreamTTS")
        self.assertEqual(p1.room, "书房")
        self.assertEqual(p1.send_interval_ms, 50)
        p2 = cfg.device_profile("02:76:74:00:00:02")
        self.assertEqual(p2.tts_name, "EdgeTTS")
        self.assertEqual(p2.tts_config["type"], "edge")

    def test_silence_trimmer_keeps_speech_and_trims_edges(self):
        trimmer = SilenceTrimmer(sample_rate=24000)
        silence = b"\x00\x00" * 12000  # 500 ms silence
        loud = np.full(2400, 4000, dtype="<i2").tobytes()  # 100 ms loud
        out = trimmer.push(silence) + trimmer.push(loud) + trimmer.push(silence) + trimmer.finish()
        # 30 ms lead + 100 ms loud + 250 ms tail = 380 ms (9120 samples = 18240 bytes)
        self.assertEqual(len(out), (720 + 2400 + 6000) * 2)

    def test_health_sanitize_allowlist(self):
        clean = sanitize({"schema": 1, "rms": 120.5, "secret_token": "drop-me", "window": {"wake_hits": 2, "bad": 9}})
        self.assertEqual(clean, {"schema": 1, "rms": 120.5, "window": {"wake_hits": 2}})


class TestTTSFallback(unittest.IsolatedAsyncioTestCase):
    async def test_edge_failure_falls_back_to_sherpa(self):
        pipe = DeviceTTSPipeline(
            {"type": "edge_stream", "voice": "zh-CN-XiaoxiaoNeural"},
            {"type": "index_stream", "api_url": "http://sherpa-tts:11996/tts"},
        )
        pipe.primary = FakePCMBackend(fail=True, tag="edge_stream")
        pipe._edge_fallback = FakePCMBackend(fail=True, tag="edge")
        pipe._sherpa_fallback = FakePCMBackend(fail=False, tag="sherpa")

        chunks = []
        async for pcm in pipe.stream_pcm("测试回退", asyncio.Event()):
            chunks.append(pcm)
        self.assertTrue(chunks)
        self.assertEqual(pipe._sherpa_fallback.texts, ["测试回退"])


class TestProtocolE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        raw = {
            "selected_module": {"ASR": "SherpaASR", "LLM": "HermesAgentLLM", "TTS": "SherpaOnnxTTS"},
            "voice_devices": {
                "02:76:74:00:00:01": {
                    "output": "server_audio",
                    "tts": "SherpaOnnxTTS",
                    "room": "书房",
                    "reply_style": "sentence",
                    "send_interval_ms": 10,
                }
            },
        }
        self.config = GatewayConfig(raw, base_dir=Path(self._tmp.name))
        self.config.health_log_path = Path(self._tmp.name) / "audio-health.jsonl"
        self.asr = FakeASR("把灯打开")
        self.llm_provider = FakeLLMProvider()
        self.app = VoiceGatewayApp(self.config, asr=self.asr, llm=LLMBridge(self.llm_provider))

        # Patch DeviceTTSPipeline so server_audio tests run without network/sidecar.
        self._tts_patch = patch("gateway.session.DeviceTTSPipeline", self._fake_tts_pipeline)
        self._tts_patch.start()

        self.server = await websockets.serve(self.app.handle_ws, "127.0.0.1", 0, max_size=None)
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/xiaozhi/v1/"

    @staticmethod
    def _fake_tts_pipeline(*_args, **_kwargs):
        class _Pipe:
            async def warm_up(self):
                return

            async def stream_pcm(self, text: str, abort_event: asyncio.Event):
                async for pcm in FakePCMBackend().stream_pcm(text, abort_event):
                    yield pcm

            async def close(self):
                return

        return _Pipe()

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await self.app.close()
        self._tts_patch.stop()
        self._tmp.cleanup()

    async def _connect(self, device_id: str):
        headers = {
            "Authorization": "Bearer test",
            "Protocol-Version": "1",
            "Device-Id": device_id,
            "Client-Id": f"client-{device_id}",
        }
        ws = await websockets.connect(self.url, additional_headers=headers, max_size=None)
        await ws.send(json.dumps({
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
        }))
        hello = json.loads(await asyncio.wait_for(ws.recv(), 5))
        self.assertEqual(hello["type"], "hello")
        self.assertTrue(hello["session_id"])
        return ws, hello["session_id"]

    async def test_native_xiaomi_text_only_and_ping_and_health(self):
        ws, sid = await self._connect("aa:bb:cc:dd:ee:01")
        try:
            # Ping -> Pong
            await ws.send(json.dumps({"session_id": sid, "type": "ping"}))
            pong = json.loads(await asyncio.wait_for(ws.recv(), 5))
            self.assertEqual(pong["type"], "pong")

            # Audio health ignored by turn flow and logged
            await ws.send(json.dumps({"type": "audio_health", "health": {"schema": 1, "rms": 42.0}}))

            # Text turn via detect
            await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "detect", "text": "你好"}))
            events, audio_count = [], 0
            while True:
                msg = await asyncio.wait_for(ws.recv(), 5)
                if isinstance(msg, bytes):
                    audio_count += 1
                    continue
                data = json.loads(msg)
                events.append(data)
                if data.get("type") == "tts" and data.get("state") == "stop":
                    break

            self.assertEqual(audio_count, 0)
            self.assertEqual(events[0]["type"], "stt")
            self.assertEqual(events[0]["text"], "你好")
            tts_states = [e["state"] for e in events if e["type"] == "tts"]
            self.assertEqual(tts_states[0], "start")
            self.assertEqual(tts_states[-1], "stop")
            spoken = "".join(e.get("text", "") for e in events if e.get("state") == "sentence_start")
            self.assertIn("客厅灯现在是开着的", spoken)
        finally:
            await ws.close()

    async def test_server_audio_device_room_context_and_opus_frames(self):
        ws, sid = await self._connect("02:76:74:00:00:01")
        try:
            await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "detect", "text": "灯开着吗"}))
            sentences, audio_packets = [], 0
            while True:
                msg = await asyncio.wait_for(ws.recv(), 5)
                if isinstance(msg, bytes):
                    audio_packets += 1
                    continue
                data = json.loads(msg)
                if data.get("type") == "tts" and data.get("state") == "sentence_start":
                    sentences.append(data["text"])
                if data.get("type") == "tts" and data.get("state") == "stop":
                    break
            self.assertTrue(sentences)
            self.assertGreaterEqual(audio_packets, 3)
            # Verify room context was injected into the system message sent to Hermes.
            _, dialogue = self.llm_provider.calls[-1]
            self.assertIn("Device room: 书房", dialogue[0]["content"])
            self.assertIn("Reply style:", dialogue[0]["content"])
        finally:
            await ws.close()

    async def test_empty_llm_reply_still_emits_start_and_stop(self):
        # Mirrors silent music "暂停" command where hermes.py yields nothing.
        self.llm_provider.chunks_fn = lambda _sid, _d: []
        ws, sid = await self._connect("aa:bb:cc:dd:ee:02")
        try:
            await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "detect", "text": "暂停"}))
            seen = []
            while True:
                data = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen.append((data.get("type"), data.get("state")))
                if data.get("type") == "tts" and data.get("state") == "stop":
                    break
            self.assertEqual(seen, [("stt", None), ("tts", "start"), ("tts", "stop")])
        finally:
            await ws.close()

    async def test_proactive_announce_to_connected_device(self):
        ws, _sid = await self._connect("02:76:74:00:00:01")
        try:
            await asyncio.sleep(0.05)
            targets = self.app.registry.find(room="书房")
            self.assertEqual(len(targets), 1)
            ann_task = asyncio.create_task(targets[0].announce("洗衣机洗完了。"))
            sentences, audio_packets = [], 0
            while True:
                msg = await asyncio.wait_for(ws.recv(), 5)
                if isinstance(msg, bytes):
                    audio_packets += 1
                    continue
                data = json.loads(msg)
                if data.get("type") == "tts" and data.get("state") == "sentence_start":
                    sentences.append(data["text"])
                if data.get("type") == "tts" and data.get("state") == "stop":
                    break
            self.assertTrue(await ann_task)
            self.assertEqual(sentences, ["洗衣机洗完了。"])
            self.assertGreaterEqual(audio_packets, 3)
        finally:
            await ws.close()

    async def test_opus_roundtrip_audio_turn(self):
        try:
            import opuslib_next as opuslib
        except ImportError:
            self.skipTest("opuslib_next not installed in local test env")
        enc = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
        pcm = (np.sin(2 * np.pi * 300 * np.arange(960) / 16000.0) * 5000).astype("<i2").tobytes()
        frame = enc.encode(pcm, 960)

        ws, sid = await self._connect("aa:bb:cc:dd:ee:03")
        try:
            await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "start", "mode": "manual"}))
            for _ in range(5):
                await ws.send(frame)
            await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "stop"}))
            stt_text = None
            while True:
                data = json.loads(await asyncio.wait_for(ws.recv(), 5))
                if data.get("type") == "stt":
                    stt_text = data.get("text")
                if data.get("type") == "tts" and data.get("state") == "stop":
                    break
            self.assertEqual(stt_text, "把灯打开")
            self.assertEqual(len(self.asr.calls), 1)
        finally:
            await ws.close()

    async def test_abort_cancels_slow_turn(self):
        import time as _time

        def slow_gen(_sid, _dialogue):
            yield "这是一段很长的故事，"
            for _ in range(30):
                _time.sleep(0.05)
                yield "接下来发生了很多事情。"

        self.llm_provider.chunks_fn = slow_gen
        ws, sid = await self._connect("aa:bb:cc:dd:ee:04")
        try:
            await ws.send(json.dumps({"session_id": sid, "type": "listen", "state": "detect", "text": "讲故事"}))
            got_first = False
            while not got_first:
                data = json.loads(await asyncio.wait_for(ws.recv(), 5))
                if data.get("type") == "tts" and data.get("state") == "sentence_start":
                    got_first = True
            await ws.send(json.dumps({"session_id": sid, "type": "abort"}))
            # Turn should emit tts:stop quickly and not hang for 1.5s+.
            stopped = False
            while not stopped:
                data = json.loads(await asyncio.wait_for(ws.recv(), 2))
                if data.get("type") == "tts" and data.get("state") == "stop":
                    stopped = True
            self.assertTrue(stopped)
        finally:
            await ws.close()

    async def test_http_health_status_and_announce(self):
        from aiohttp.test_utils import TestClient, TestServer

        self.config.announce_token = "secret-123"
        async with TestClient(TestServer(self.app.build_http_app())) as client:
            resp = await client.get("/health")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertEqual(body["status"], "ok")

            # Unauthorized announce rejected
            resp = await client.post("/announce", json={"room": "书房", "text": "hi"})
            self.assertEqual(resp.status, 401)

            ws, _sid = await self._connect("02:76:74:00:00:01")
            try:
                await asyncio.sleep(0.05)
                resp = await client.get("/status")
                status = await resp.json()
                self.assertEqual(len(status["devices"]), 1)
                self.assertEqual(status["devices"][0]["room"], "书房")

                ann_req = asyncio.create_task(
                    client.post(
                        "/announce",
                        json={"room": "书房", "text": "门没关好。"},
                        headers={"Authorization": "Bearer secret-123"},
                    )
                )
                seen_text = ""
                while True:
                    msg = await asyncio.wait_for(ws.recv(), 5)
                    if isinstance(msg, bytes):
                        continue
                    data = json.loads(msg)
                    if data.get("state") == "sentence_start":
                        seen_text += data.get("text", "")
                    if data.get("state") == "stop":
                        break
                ann_resp = await ann_req
                self.assertEqual(ann_resp.status, 200)
                self.assertEqual(seen_text, "门没关好。")
            finally:
                await ws.close()


if __name__ == "__main__":
    unittest.main()
