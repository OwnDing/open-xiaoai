"""Per-WebSocket device session implementing the Xiaozhi v1 voice protocol."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import time
from typing import Any
import uuid

from .config import DeviceProfile, GatewayConfig
from .health import AudioHealthSink
from .llm import LLMBridge
from .opus import ContinuousOpusEncoder24k, OpusDecoder16k, UPLINK_RATE, pcm16_to_wav
from .text import SentenceSplitter, clean_markdown, spoken_len
from .tts import DeviceTTSPipeline
from .voiceprint import VoiceprintClient

log = logging.getLogger("voice-gateway.session")

WEEKDAYS = "一二三四五六日"
# Send the first few Opus packets immediately to prime the terminal's jitter
# buffer before pacing at send_interval_ms.
PREBUFFER_PACKETS = 4


class SessionRegistry:
    """Tracks live WebSocket device sessions for /status and /announce."""

    def __init__(self) -> None:
        self._sessions: dict[str, "DeviceSession"] = {}

    def add(self, session: "DeviceSession") -> None:
        self._sessions[session.session_id] = session

    def remove(self, session: "DeviceSession") -> None:
        if self._sessions.get(session.session_id) is session:
            self._sessions.pop(session.session_id, None)

    def all(self) -> list["DeviceSession"]:
        return list(self._sessions.values())

    def find(self, device_id: str | None = None, room: str | None = None) -> list["DeviceSession"]:
        wanted_dev = (device_id or "").strip().lower()
        wanted_room = (room or "").strip()
        matches: list["DeviceSession"] = []
        for s in self._sessions.values():
            if wanted_dev and s.device_id.lower() != wanted_dev:
                continue
            if wanted_room and s.profile.room != wanted_room:
                continue
            matches.append(s)
        return matches


class DeviceSession:
    """Manages one connected voice terminal (小爱桥接 / PC voice-terminal / ESP32)."""

    def __init__(
        self,
        ws: Any,
        config: GatewayConfig,
        asr: Any,
        llm: LLMBridge,
        voiceprint: VoiceprintClient,
        health: AudioHealthSink,
        registry: SessionRegistry,
        device_id: str,
        client_id: str,
    ):
        self.ws = ws
        self.config = config
        self.asr = asr
        self.llm = llm
        self.voiceprint = voiceprint
        self.health = health
        self.registry = registry
        self.device_id = device_id or ""
        self.client_id = client_id or ""
        self.session_id = str(uuid.uuid4())
        self.profile: DeviceProfile = config.device_profile(self.device_id)
        self.connected_at = time.time()
        self.turns = 0
        self.last_stt = ""
        self.last_reply = ""

        self._send_lock = asyncio.Lock()
        self._listening = False
        self._opus_frames: list[bytes] = []
        self._opus_packets_total = 0
        self._opus_bytes_total = 0
        self._decoder = OpusDecoder16k()
        self._encoder = ContinuousOpusEncoder24k() if self.profile.server_audio else None
        self._tts = (
            DeviceTTSPipeline(self.profile.tts_config, config.fallback_sherpa_config)
            if self.profile.server_audio
            else None
        )
        self._history: list[dict[str, str]] = []
        self._history_at = 0.0
        self._turn_task: asyncio.Task[None] | None = None
        self._turn_abort = asyncio.Event()
        self._closed = False
        self._warmup_task: asyncio.Task[None] | None = None
        # Max 60 ms packets buffered per utterance (~2x max_audio_s for safety).
        self._max_frames = max(50, int(config.max_audio_s * 1000 // 60) + 20)

    def status_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "client_id": self.client_id,
            "room": self.profile.room,
            "output": "server_audio" if self.profile.server_audio else "native_xiaomi",
            "tts": self.profile.tts_name if self.profile.server_audio else "native",
            "connected_s": round(time.time() - self.connected_at, 1),
            "turns": self.turns,
            "busy": self._turn_task is not None and not self._turn_task.done(),
            "last_stt": self.last_stt,
            "last_reply": self.last_reply[:80],
        }

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        data = json.dumps({"session_id": self.session_id, **payload}, ensure_ascii=False)
        async with self._send_lock:
            if not self._closed:
                await self.ws.send(data)

    async def send_audio(self, packet: bytes) -> None:
        if self._closed:
            return
        async with self._send_lock:
            if not self._closed:
                await self.ws.send(packet)

    # ---- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        self.registry.add(self)
        log.info(
            "connected device=%s session=%s output=%s tts=%s room=%s",
            self.device_id or "-",
            self.session_id[:8],
            "server_audio" if self.profile.server_audio else "native_xiaomi",
            self.profile.tts_name if self.profile.server_audio else "native",
            self.profile.room or "-",
        )
        if self._tts is not None:
            self._warmup_task = asyncio.create_task(self._tts.warm_up())
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    self._on_binary(message)
                elif isinstance(message, str):
                    await self._on_text(message)
        except Exception as exc:
            log.info("disconnected device=%s session=%s (%s)", self.device_id or "-", self.session_id[:8], exc)
        finally:
            self._closed = True
            self.registry.remove(self)
            await self._cancel_turn()
            if self._warmup_task is not None and not self._warmup_task.done():
                self._warmup_task.cancel()
            if self._tts is not None:
                await self._tts.close()
            log.info("closed device=%s session=%s turns=%d", self.device_id or "-", self.session_id[:8], self.turns)

    def _on_binary(self, packet: bytes) -> None:
        self._opus_packets_total += 1
        self._opus_bytes_total += len(packet)
        if self._listening and len(self._opus_frames) < self._max_frames:
            self._opus_frames.append(packet)

    async def _on_text(self, raw: str) -> None:
        # Fast path for audio_health diagnostics (matches audio_health.py).
        if len(raw) <= 16384 and '"audio_health"' in raw:
            try:
                pkt = json.loads(raw)
                if isinstance(pkt, dict) and pkt.get("type") == "audio_health":
                    self.health.record(
                        self.device_id,
                        self.session_id,
                        pkt.get("health"),
                        self._opus_packets_total,
                        self._opus_bytes_total,
                    )
                    return
            except ValueError:
                pass

        try:
            data = json.loads(raw)
        except ValueError:
            log.warning("ignoring non-JSON message from %s: %.80s", self.device_id, raw)
            return
        if not isinstance(data, dict):
            return

        msg_type = data.get("type")
        if msg_type == "ping":
            await self.send_json({"type": "pong"})
            return
        if msg_type == "hello":
            await self.send_json(
                {
                    "type": "hello",
                    "version": 1,
                    "transport": "websocket",
                    "audio_params": {
                        "format": "opus",
                        "sample_rate": 24000,
                        "channels": 1,
                        "frame_duration": 60,
                    },
                }
            )
            return
        if msg_type == "abort":
            await self._cancel_turn()
            return
        if msg_type == "listen":
            state = data.get("state")
            if state == "start":
                await self._cancel_turn()
                self._opus_frames.clear()
                self._listening = True
                log.debug("listen start device=%s mode=%s", self.device_id, data.get("mode", "manual"))
            elif state == "stop":
                self._listening = False
                frames = list(self._opus_frames)
                self._opus_frames.clear()
                if frames:
                    self._start_turn(self._run_audio_turn(frames))
            elif state == "detect":
                text = str(data.get("text") or "").strip()
                if text:
                    await self._cancel_turn()
                    self._start_turn(self._run_text_turn(text))
            return
        if msg_type == "iot":
            return
        log.debug("unhandled message from %s: %s", self.device_id, msg_type)

    # ---- turn management ---------------------------------------------------

    def _start_turn(self, coro) -> None:
        self._turn_abort = asyncio.Event()
        self._turn_task = asyncio.create_task(coro)

    async def _cancel_turn(self) -> None:
        self._listening = False
        self._opus_frames.clear()
        self._turn_abort.set()
        task = self._turn_task
        self._turn_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    def _build_context_message(self) -> dict[str, str]:
        now = datetime.now()
        lines = [
            f"- Current time: {now:%H:%M}",
            f"- Today's date: {now:%Y-%m-%d} 星期{WEEKDAYS[now.weekday()]}",
        ]
        lines.extend(self.config.context_lines(self.profile))
        return {"role": "system", "content": "<context>\n" + "\n".join(lines) + "\n</context>"}

    def _get_history(self) -> list[dict[str, str]]:
        if self._history and time.monotonic() - self._history_at > self.config.history_idle_reset_s:
            self._history.clear()
        return [dict(m) for m in self._history]

    def _append_history(self, user_text: str, reply_text: str) -> None:
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": reply_text})
        limit = self.config.history_max_messages
        if limit > 0 and len(self._history) > limit:
            self._history = self._history[-limit:]
        self._history_at = time.monotonic()

    async def _run_audio_turn(self, frames: list[bytes]) -> None:
        abort = self._turn_abort
        t0 = time.perf_counter()
        max_samples = int(self.config.max_audio_s * UPLINK_RATE)
        pcm = await asyncio.to_thread(self._decoder.decode_frames, frames, max_samples)
        if not pcm or abort.is_set():
            return

        # Run ASR and optional voiceprint identification in parallel so
        # voiceprint adds zero latency when faster than ASR.
        asr_task = asyncio.create_task(self.asr.transcribe_pcm16(pcm, UPLINK_RATE))
        vp_task = (
            asyncio.create_task(
                self.voiceprint.identify(pcm16_to_wav(pcm, UPLINK_RATE), self.session_id, self.device_id)
            )
            if self.voiceprint.enabled
            else None
        )
        try:
            text, asr_s = await asr_task
            if vp_task is not None:
                await vp_task
        except asyncio.CancelledError:
            asr_task.cancel()
            if vp_task is not None:
                vp_task.cancel()
            raise

        if abort.is_set():
            return
        text = text.strip()
        if not text or spoken_len(text) == 0:
            log.info("ASR empty device=%s frames=%d %.2fs", self.device_id, len(frames), asr_s)
            return
        log.info("ASR device=%s %.2fs (total %.2fs): %s", self.device_id, asr_s, time.perf_counter() - t0, text)
        await self._run_text_turn(text)

    async def _run_text_turn(self, text: str) -> None:
        abort = self._turn_abort
        started = time.perf_counter()
        self.turns += 1
        self.last_stt = text
        self.last_reply = ""

        await self.send_json({"type": "stt", "text": text})
        if abort.is_set():
            return

        dialogue = [self._build_context_message(), *self._get_history(), {"role": "user", "content": text}]
        turn_state = {"tts_started": False}
        reply_parts: list[str] = []

        try:
            if not self.profile.server_audio:
                await self._stream_text_only(dialogue, abort, reply_parts, turn_state)
            else:
                await self._stream_server_audio(dialogue, abort, reply_parts, turn_state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Turn failed device=%s text=%r: %s", self.device_id, text[:40], exc)
            if not abort.is_set():
                fallback = "抱歉，刚才处理出了点问题，你再说一遍吧。"
                if not turn_state["tts_started"]:
                    await self.send_json({"type": "tts", "state": "start"})
                    turn_state["tts_started"] = True
                if not self.profile.server_audio:
                    await self.send_json({"type": "tts", "state": "sentence_start", "text": fallback})
                else:
                    await self._speak_single_audio(fallback, abort)
                reply_parts.append(fallback)
        finally:
            if turn_state["tts_started"] and not self._closed:
                try:
                    await self.send_json({"type": "tts", "state": "stop"})
                except Exception:
                    pass

        full_reply = "".join(reply_parts).strip()
        self.last_reply = full_reply
        if full_reply and not abort.is_set():
            self._append_history(text, full_reply)
        log.info(
            "turn done device=%s %.2fs aborted=%s reply=%s",
            self.device_id,
            time.perf_counter() - started,
            abort.is_set(),
            full_reply[:60],
        )

    async def _stream_text_only(
        self,
        dialogue: list[dict[str, str]],
        abort: asyncio.Event,
        reply_parts: list[str],
        turn_state: dict[str, bool],
    ) -> None:
        splitter = SentenceSplitter()

        async def emit(seg: str) -> None:
            if abort.is_set() or not seg:
                return
            if not turn_state["tts_started"]:
                await self.send_json({"type": "tts", "state": "start"})
                turn_state["tts_started"] = True
            await self.send_json({"type": "tts", "state": "sentence_start", "text": seg})
            reply_parts.append(seg)

        async for chunk in self.llm.stream_reply(self.session_id, dialogue, abort):
            if abort.is_set():
                return
            for seg in splitter.feed(chunk):
                await emit(seg)
        if not abort.is_set():
            for seg in splitter.flush():
                await emit(seg)
            # Even when a shortcut intentionally speaks nothing (e.g. music "暂停"),
            # send start+stop so the XiaoAi bridge finishes its turn cleanly.
            if not turn_state["tts_started"]:
                await self.send_json({"type": "tts", "state": "start"})
                turn_state["tts_started"] = True

    async def _stream_server_audio(
        self,
        dialogue: list[dict[str, str]],
        abort: asyncio.Event,
        reply_parts: list[str],
        turn_state: dict[str, bool],
    ) -> None:
        assert self._tts is not None and self._encoder is not None
        self._encoder.reset()
        seg_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=8)
        llm_error: list[Exception] = []

        async def producer() -> None:
            splitter = SentenceSplitter()
            try:
                async for chunk in self.llm.stream_reply(self.session_id, dialogue, abort):
                    if abort.is_set():
                        return
                    for seg in splitter.feed(chunk):
                        await seg_queue.put(seg)
                if not abort.is_set():
                    for seg in splitter.flush():
                        await seg_queue.put(seg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                llm_error.append(exc)
            finally:
                await seg_queue.put(None)

        prod_task = asyncio.create_task(producer())
        sent_packets = 0
        interval_s = self.profile.send_interval_ms / 1000.0
        next_deadline = 0.0

        async def send_opus_packet(pkt: bytes) -> None:
            nonlocal sent_packets, next_deadline
            if abort.is_set():
                return
            now = time.monotonic()
            if sent_packets < PREBUFFER_PACKETS:
                await self.send_audio(pkt)
                sent_packets += 1
                next_deadline = now + interval_s
            else:
                if now < next_deadline:
                    await asyncio.sleep(next_deadline - now)
                if abort.is_set():
                    return
                await self.send_audio(pkt)
                sent_packets += 1
                # Avoid falling permanently behind if a slow TTS gap occurred.
                next_deadline = max(next_deadline + interval_s, time.monotonic())

        try:
            while True:
                seg = await seg_queue.get()
                if seg is None:
                    break
                if abort.is_set():
                    break
                if not turn_state["tts_started"]:
                    await self.send_json({"type": "tts", "state": "start"})
                    turn_state["tts_started"] = True
                reply_parts.append(seg)
                announced_seg = False
                async for pcm in self._tts.stream_pcm(seg, abort):
                    if abort.is_set():
                        break
                    if not announced_seg:
                        await self.send_json({"type": "tts", "state": "sentence_start", "text": seg})
                        announced_seg = True
                    for pkt in self._encoder.encode(pcm):
                        await send_opus_packet(pkt)
                if not announced_seg and not abort.is_set():
                    # Still send text notification even if TTS produced no audio.
                    await self.send_json({"type": "tts", "state": "sentence_start", "text": seg})

            if not abort.is_set():
                if llm_error:
                    raise llm_error[0]
                if not turn_state["tts_started"]:
                    await self.send_json({"type": "tts", "state": "start"})
                    turn_state["tts_started"] = True
                for pkt in self._encoder.flush():
                    await send_opus_packet(pkt)
        finally:
            if not prod_task.done():
                prod_task.cancel()
                await asyncio.gather(prod_task, return_exceptions=True)

    async def _speak_single_audio(self, text: str, abort: asyncio.Event) -> None:
        if self._tts is None or self._encoder is None:
            return
        self._encoder.reset()
        await self.send_json({"type": "tts", "state": "sentence_start", "text": text})
        interval_s = self.profile.send_interval_ms / 1000.0
        sent = 0
        async for pcm in self._tts.stream_pcm(text, abort):
            if abort.is_set():
                return
            for pkt in self._encoder.encode(pcm):
                await self.send_audio(pkt)
                sent += 1
                if sent >= PREBUFFER_PACKETS:
                    await asyncio.sleep(interval_s)
        for pkt in self._encoder.flush():
            if abort.is_set():
                return
            await self.send_audio(pkt)

    # ---- proactive announcement (POST /announce) ---------------------------

    async def announce(self, text: str) -> bool:
        """Push a proactive spoken announcement to this terminal if idle."""
        clean = clean_markdown(text).strip()
        if not clean or self._closed:
            return False
        if self._turn_task is not None and not self._turn_task.done():
            return False
        abort = asyncio.Event()
        self._turn_abort = abort

        async def _run() -> None:
            tts_started = False
            try:
                await self.send_json({"type": "tts", "state": "start"})
                tts_started = True
                if not self.profile.server_audio:
                    await self.send_json({"type": "tts", "state": "sentence_start", "text": clean})
                else:
                    await self._speak_single_audio(clean, abort)
            finally:
                if tts_started and not self._closed:
                    try:
                        await self.send_json({"type": "tts", "state": "stop"})
                    except Exception:
                        pass

        self._turn_task = asyncio.create_task(_run())
        await self._turn_task
        return True
