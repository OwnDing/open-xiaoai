"""Streaming TTS backends (24 kHz s16le mono PCM) with automatic offline fallback.

Supported backends:
- edge_stream: persistent Edge TTS WebSocket + in-process streaming MP3 decode (PyAV)
  + SilenceTrimmer. Falls back to stock edge_tts, then offline Sherpa TTS.
- edge: stock edge_tts + streaming MP3 decode + SilenceTrimmer. Falls back to Sherpa.
- index_stream / sherpa: streams raw 24 kHz PCM from deploy/sherpa-tts HTTP sidecar.
- sherpa_local: optional lazy in-process sherpa-onnx VITS model (no sidecar needed).
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator
from xml.sax.saxutils import escape

import aiohttp
import certifi
import numpy as np

log = logging.getLogger("voice-gateway.tts")

TARGET_SAMPLE_RATE = 24000
EDGE_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
EDGE_CHUNK_TIMEOUT = 10.0
LEAD_KEEP_MS = 30
TAIL_KEEP_MS = 250
SILENCE_LEVEL = 100  # int16 amplitude (~ -50 dBFS)


class SilenceTrimmer:
    """Trim leading/trailing silence of a streamed 16-bit mono PCM segment."""

    def __init__(self, sample_rate: int = TARGET_SAMPLE_RATE):
        self._lead_keep = sample_rate * LEAD_KEEP_MS // 1000 * 2
        self._tail_keep = sample_rate * TAIL_KEEP_MS // 1000 * 2
        self._started = False
        self._held = b""
        self._odd = b""

    def push(self, pcm: bytes) -> bytes:
        if not pcm:
            return b""
        data = self._held + self._odd + pcm
        usable = len(data) // 2 * 2
        data, self._odd = data[:usable], data[usable:]
        if not data:
            return b""
        samples = np.frombuffer(data, dtype="<i2")
        loud = np.flatnonzero(np.abs(samples.astype(np.int32)) > SILENCE_LEVEL)
        if not len(loud):
            self._held = data if self._started else data[-self._lead_keep:]
            return b""
        start = 0
        if not self._started:
            self._started = True
            start = max(0, int(loud[0]) * 2 - self._lead_keep)
        end = (int(loud[-1]) + 1) * 2
        self._held = data[end:]
        return data[start:end]

    def finish(self) -> bytes:
        tail = self._held[: self._tail_keep] if self._started else b""
        self._held = self._odd = b""
        return tail


class MP3StreamDecoder:
    """Incremental MP3 -> 24 kHz s16le mono PCM decoder using PyAV (zero subprocess)."""

    def __init__(self, sample_rate: int = TARGET_SAMPLE_RATE):
        import av

        self._codec = av.CodecContext.create("mp3", "r")
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)

    def _frames_to_pcm(self, frames) -> bytes:
        out = bytearray()
        for frame in frames:
            for resampled in self._resampler.resample(frame):
                arr = np.asarray(resampled.to_ndarray(), dtype="<i2").reshape(-1)
                out.extend(arr.tobytes())
        return bytes(out)

    def push(self, mp3_bytes: bytes) -> bytes:
        if not mp3_bytes:
            return b""
        out = bytearray()
        for packet in self._codec.parse(mp3_bytes):
            if packet.size > 0:
                out.extend(self._frames_to_pcm(self._codec.decode(packet)))
        return bytes(out)

    def finish(self) -> bytes:
        out = bytearray()
        for packet in self._codec.parse(None):
            if packet.size > 0:
                out.extend(self._frames_to_pcm(self._codec.decode(packet)))
        out.extend(self._frames_to_pcm(self._codec.decode(None)))
        for resampled in self._resampler.resample(None):
            arr = np.asarray(resampled.to_ndarray(), dtype="<i2").reshape(-1)
            out.extend(arr.tobytes())
        return bytes(out)


def _has_pyav() -> bool:
    try:
        import av  # noqa: F401
        return True
    except ImportError:
        return False


def _ffmpeg_decode_mp3(mp3_bytes: bytes, sample_rate: int = TARGET_SAMPLE_RATE) -> bytes:
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "mp3", "-i", "pipe:0",
            "-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "pipe:1",
        ],
        input=mp3_bytes,
        capture_output=True,
        check=True,
    )
    return proc.stdout


class EdgeStreamBackend:
    """Persistent WebSocket Edge TTS connection per device session."""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz"):
        import edge_tts

        self.voice = voice
        self._tts_config = edge_tts.Communicate(
            "x", voice=voice, rate=rate, volume=volume, pitch=pitch
        ).tts_config
        self._ssl = ssl.create_default_context(cafile=certifi.where())
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_lock = asyncio.Lock()
        self._use_pyav = _has_pyav()

    async def _connect(self) -> aiohttp.ClientWebSocketResponse:
        from edge_tts.communicate import connect_id
        from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
        from edge_tts.drm import DRM

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(trust_env=True)
        for attempt in (1, 2):
            url = (
                f"{WSS_URL}&ConnectionId={connect_id()}"
                f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
            )
            try:
                return await self._session.ws_connect(
                    url, compress=15, headers=DRM.headers_with_muid(WSS_HEADERS), ssl=self._ssl
                )
            except aiohttp.ClientResponseError as exc:
                if exc.status != 403 or attempt == 2:
                    raise
                DRM.handle_client_response_error(exc)
        raise RuntimeError("Edge WebSocket connect failed")

    async def _ensure_ws(self) -> aiohttp.ClientWebSocketResponse:
        async with self._ws_lock:
            if self._ws is None or self._ws.closed:
                started = time.monotonic()
                self._ws = await self._connect()
                log.debug("Edge WS connected in %.2fs", time.monotonic() - started)
            return self._ws

    async def _drop_ws(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None and not ws.closed:
            try:
                await ws.close()
            except Exception:
                pass

    async def warm_up(self) -> None:
        try:
            await self._ensure_ws()
        except Exception as exc:
            log.warning("Edge warm-up failed: %s", exc)

    async def stream_pcm(self, text: str, abort_event: asyncio.Event) -> AsyncIterator[bytes]:
        from edge_tts.communicate import (
            connect_id,
            date_to_string,
            get_headers_and_data,
            mkssml,
            remove_incompatible_characters,
            ssml_headers_plus_data,
        )

        for attempt in (1, 2):
            got_audio = False
            decoder = MP3StreamDecoder(TARGET_SAMPLE_RATE) if self._use_pyav else None
            trimmer = SilenceTrimmer(TARGET_SAMPLE_RATE)
            mp3_fallback = bytearray()
            try:
                ws = await self._ensure_ws()
                await ws.send_str(
                    f"X-Timestamp:{date_to_string()}\r\nContent-Type:application/json; charset=utf-8\r\n"
                    "Path:speech.config\r\n\r\n"
                    '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                    '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
                    f'"outputFormat":"{EDGE_OUTPUT_FORMAT}"' "}}}}\r\n"
                )
                ssml = mkssml(self._tts_config, escape(remove_incompatible_characters(text)))
                await ws.send_str(ssml_headers_plus_data(connect_id(), date_to_string(), ssml))

                while True:
                    if abort_event.is_set():
                        await self._drop_ws()
                        return
                    msg = await asyncio.wait_for(ws.receive(), timeout=EDGE_CHUNK_TIMEOUT)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if "Path:turn.end" in msg.data:
                            break
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        header_len = int.from_bytes(msg.data[:2], "big")
                        headers, data = get_headers_and_data(msg.data, header_len)
                        if headers.get(b"Path") == b"audio" and data:
                            got_audio = True
                            if decoder is not None:
                                pcm = trimmer.push(decoder.push(data))
                                if pcm:
                                    yield pcm
                            else:
                                mp3_fallback.extend(data)
                    else:
                        raise ConnectionError(f"Edge WS closed ({msg.type.name})")

                if abort_event.is_set():
                    return
                if decoder is not None:
                    tail = trimmer.push(decoder.finish()) + trimmer.finish()
                    if tail:
                        yield tail
                elif mp3_fallback:
                    raw = await asyncio.to_thread(_ffmpeg_decode_mp3, bytes(mp3_fallback), TARGET_SAMPLE_RATE)
                    pcm = trimmer.push(raw) + trimmer.finish()
                    if pcm:
                        yield pcm
                return
            except asyncio.CancelledError:
                await self._drop_ws()
                raise
            except Exception as exc:
                await self._drop_ws()
                if got_audio or attempt == 2 or abort_event.is_set():
                    raise
                log.warning("EdgeStream failed (%s); retrying on a new connection", exc)

    async def close(self) -> None:
        await self._drop_ws()
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


class EdgeStockBackend:
    """Stock edge_tts.Communicate streaming backend."""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz"):
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch
        self._use_pyav = _has_pyav()

    async def stream_pcm(self, text: str, abort_event: asyncio.Event) -> AsyncIterator[bytes]:
        import edge_tts

        comm = edge_tts.Communicate(text, voice=self.voice, rate=self.rate, volume=self.volume, pitch=self.pitch)
        decoder = MP3StreamDecoder(TARGET_SAMPLE_RATE) if self._use_pyav else None
        trimmer = SilenceTrimmer(TARGET_SAMPLE_RATE)
        mp3_fallback = bytearray()
        async for item in comm.stream():
            if abort_event.is_set():
                return
            if item.get("type") == "audio" and item.get("data"):
                data = item["data"]
                if decoder is not None:
                    pcm = trimmer.push(decoder.push(data))
                    if pcm:
                        yield pcm
                else:
                    mp3_fallback.extend(data)
        if abort_event.is_set():
            return
        if decoder is not None:
            tail = trimmer.push(decoder.finish()) + trimmer.finish()
            if tail:
                yield tail
        elif mp3_fallback:
            raw = await asyncio.to_thread(_ffmpeg_decode_mp3, bytes(mp3_fallback), TARGET_SAMPLE_RATE)
            pcm = trimmer.push(raw) + trimmer.finish()
            if pcm:
                yield pcm

    async def close(self) -> None:
        return


class SherpaHttpBackend:
    """Calls deploy/sherpa-tts HTTP sidecar (returns raw 24 kHz s16le mono PCM)."""

    def __init__(self, api_url: str = "http://sherpa-tts:11996/tts", voice: str = "xiao_ya", timeout_s: float = 30.0):
        self.api_url = api_url
        self.voice = voice
        self.timeout_s = timeout_s
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def stream_pcm(self, text: str, abort_event: asyncio.Event) -> AsyncIterator[bytes]:
        timeout = aiohttp.ClientTimeout(total=self.timeout_s)
        session = self._get_session()
        async with session.post(
            self.api_url,
            json={"text": text, "character": self.voice},
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"sherpa-tts HTTP {resp.status}: {body[:120]}")
            async for chunk in resp.content.iter_chunked(5760):
                if abort_event.is_set():
                    return
                if chunk:
                    yield chunk

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


class SherpaLocalBackend:
    """Lazy in-process Sherpa-ONNX VITS TTS backend (optional, zero sidecar)."""

    def __init__(self, model_dir: str | Path, num_threads: int = 2, speed: float = 1.0):
        self.model_dir = Path(model_dir)
        self.num_threads = max(1, int(num_threads))
        self.speed = float(speed)
        self._tts = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        if self._tts is not None:
            return self._tts
        import sherpa_onnx

        onnx_files = sorted(self.model_dir.glob("*.onnx"))
        if not onnx_files:
            raise FileNotFoundError(f"No VITS .onnx file found in {self.model_dir}")
        rule_fsts = ",".join(
            str(self.model_dir / f)
            for f in ("phone.fst", "date.fst", "number.fst")
            if (self.model_dir / f).is_file()
        )
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(onnx_files[0]),
                    lexicon=str(self.model_dir / "lexicon.txt"),
                    tokens=str(self.model_dir / "tokens.txt"),
                ),
                num_threads=self.num_threads,
                provider="cpu",
                debug=False,
            ),
            rule_fsts=rule_fsts,
            max_num_sentences=1,
        )
        self._tts = sherpa_onnx.OfflineTts(cfg)
        log.info("Loaded local Sherpa TTS from %s", self.model_dir)
        return self._tts

    def _synthesize_sync(self, text: str) -> bytes:
        import sherpa_onnx
        import soxr

        with self._lock:
            tts = self._ensure_loaded()
            gen_cfg = sherpa_onnx.GenerationConfig()
            gen_cfg.sid = 0
            gen_cfg.speed = self.speed
            gen_cfg.silence_scale = 0.2
            audio = tts.generate(text, gen_cfg)
        if not len(audio.samples):
            return b""
        samples = np.asarray(audio.samples, dtype=np.float32)
        if audio.sample_rate != TARGET_SAMPLE_RATE:
            samples = soxr.resample(samples, audio.sample_rate, TARGET_SAMPLE_RATE, quality="HQ")
        samples = np.clip(samples, -1.0, 1.0)
        return (samples * 32767.0).astype("<i2").tobytes()

    async def stream_pcm(self, text: str, abort_event: asyncio.Event) -> AsyncIterator[bytes]:
        pcm = await asyncio.to_thread(self._synthesize_sync, text)
        if abort_event.is_set() or not pcm:
            return
        yield pcm

    async def close(self) -> None:
        return


def build_tts_backend(cfg: dict[str, Any]):
    kind = str(cfg.get("type") or "index_stream").strip().lower()
    if kind == "edge_stream":
        return EdgeStreamBackend(
            voice=str(cfg.get("voice") or "zh-CN-XiaoxiaoNeural"),
            rate=str(cfg.get("rate") or "+0%"),
            volume=str(cfg.get("volume") or "+0%"),
            pitch=str(cfg.get("pitch") or "+0Hz"),
        )
    if kind == "edge":
        return EdgeStockBackend(
            voice=str(cfg.get("voice") or "zh-CN-XiaoxiaoNeural"),
            rate=str(cfg.get("rate") or "+0%"),
            volume=str(cfg.get("volume") or "+0%"),
            pitch=str(cfg.get("pitch") or "+0Hz"),
        )
    if kind == "sherpa_local" or (kind in ("sherpa", "index_stream") and cfg.get("model_dir") and not cfg.get("api_url")):
        return SherpaLocalBackend(
            model_dir=cfg["model_dir"],
            num_threads=int(cfg.get("num_threads") or 2),
            speed=float(cfg.get("speed") or 1.0),
        )
    return SherpaHttpBackend(
        api_url=str(cfg.get("api_url") or "http://sherpa-tts:11996/tts"),
        voice=str(cfg.get("voice") or "xiao_ya"),
    )


class DeviceTTSPipeline:
    """Per-session TTS runner with automatic fallback (edge_stream -> edge -> sherpa)."""

    def __init__(self, primary_cfg: dict[str, Any], fallback_sherpa_cfg: dict[str, Any] | None = None):
        self.primary_type = str(primary_cfg.get("type") or "index_stream").strip().lower()
        self.primary = build_tts_backend(primary_cfg)
        self._edge_fallback = (
            EdgeStockBackend(
                voice=str(primary_cfg.get("voice") or "zh-CN-XiaoxiaoNeural"),
                rate=str(primary_cfg.get("rate") or "+0%"),
                volume=str(primary_cfg.get("volume") or "+0%"),
                pitch=str(primary_cfg.get("pitch") or "+0Hz"),
            )
            if self.primary_type == "edge_stream"
            else None
        )
        self._sherpa_fallback = (
            build_tts_backend(fallback_sherpa_cfg)
            if fallback_sherpa_cfg and self.primary_type in ("edge_stream", "edge")
            else None
        )

    async def warm_up(self) -> None:
        if hasattr(self.primary, "warm_up"):
            await self.primary.warm_up()

    async def stream_pcm(self, text: str, abort_event: asyncio.Event) -> AsyncIterator[bytes]:
        candidates = [self.primary]
        if self._edge_fallback is not None:
            candidates.append(self._edge_fallback)
        if self._sherpa_fallback is not None:
            candidates.append(self._sherpa_fallback)

        last_exc: Exception | None = None
        for idx, backend in enumerate(candidates):
            if abort_event.is_set():
                return
            emitted = False
            try:
                async for pcm in backend.stream_pcm(text, abort_event):
                    if pcm:
                        emitted = True
                        yield pcm
                return
            except Exception as exc:
                last_exc = exc
                if emitted or abort_event.is_set() or idx + 1 >= len(candidates):
                    log.error("TTS failed (%s) on %r: %s", type(backend).__name__, text[:30], exc)
                    return
                log.warning(
                    "TTS %s failed before audio (%s); falling back to %s",
                    type(backend).__name__,
                    exc,
                    type(candidates[idx + 1]).__name__,
                )
        if last_exc is not None:
            log.error("All TTS backends failed for %r: %s", text[:30], last_exc)

    async def close(self) -> None:
        for backend in (self.primary, self._edge_fallback, self._sherpa_fallback):
            if backend is not None:
                try:
                    await backend.close()
                except Exception:
                    pass
