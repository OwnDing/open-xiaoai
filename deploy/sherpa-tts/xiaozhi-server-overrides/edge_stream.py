"""Streaming Edge TTS for xiaozhi-esp32-server (installed as core/providers/tts/edge_stream.py).

The stock `edge` provider opens a new WebSocket for every sentence (~0.6 s of
TLS and handshake) and waits for the whole MP3 before decoding it. This one:

- keeps one connection per device connection, opened when the TTS channel
  opens and reused for every sentence (reconnects when the service drops it);
- pipes the MP3 through ffmpeg while it is still arriving and sends Opus
  frames as soon as there is PCM;
- cuts the first segment of an answer at its first punctuation mark, so the
  first words are spoken while the model is still writing the rest.

If a sentence fails before any audio was produced it is retried with the
stock provider. Config (data/.config.yaml):

    TTS:
      EdgeStreamTTS:
        type: edge_stream
        voice: zh-CN-XiaoxiaoNeural
        output_dir: tmp/
"""

import asyncio
import os
import queue
import ssl
import subprocess
import threading
import time
from xml.sax.saxutils import escape

import aiohttp
import certifi
import edge_tts
import numpy as np
from edge_tts.communicate import (
    connect_id,
    date_to_string,
    get_headers_and_data,
    mkssml,
    remove_incompatible_characters,
    ssml_headers_plus_data,
)
from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
from edge_tts.drm import DRM

from config.logger import setup_logging
from core.providers.tts.dto.dto import SentenceType
from core.providers.tts.edge import TTSProvider as EdgeTTSProvider
from core.utils import textUtils
from core.utils.tts import MarkdownCleaner

TAG = __name__
logger = setup_logging()

OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
CHUNK_TIMEOUT = 10.0  # seconds without any data from Edge before giving up
# ffmpeg emits PCM ~70 ms after the first MP3 bytes with these input options.
FFMPEG_INPUT = ["-f", "mp3", "-probesize", "32", "-analyzeduration", "0", "-fflags", "nobuffer"]
# Edge pads every request with ~180 ms of silence before and ~570 ms after the
# speech, so consecutive sentences sound broken up. Keep a natural pause instead
# (Edge's own pause at a comma inside a sentence is ~330 ms).
LEAD_KEEP_MS = 30
TAIL_KEEP_MS = 250
SILENCE_LEVEL = 100  # int16 amplitude, about -50 dBFS


class SilenceTrimmer:
    """Trim leading/trailing silence of a streamed 16-bit mono PCM segment.

    Silence after the last loud sample is held back; it is released when more
    speech follows (a pause inside the sentence) and cut down to TAIL_KEEP_MS
    when the segment ends.
    """

    def __init__(self, sample_rate):
        self._lead_keep = sample_rate * LEAD_KEEP_MS // 1000 * 2
        self._tail_keep = sample_rate * TAIL_KEEP_MS // 1000 * 2
        self._started = False
        self._held = b""  # silence held back (whole samples)
        self._odd = b""  # a read can end in the middle of a sample

    def push(self, pcm: bytes) -> bytes:
        data = self._held + self._odd + pcm
        usable = len(data) // 2 * 2
        data, self._odd = data[:usable], data[usable:]
        samples = np.frombuffer(data, dtype=np.int16)
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


class TTSProvider(EdgeTTSProvider):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self._tts_config = edge_tts.Communicate(
            "x", voice=self.voice, rate=self.edge_rate, volume=self.edge_volume, pitch=self.edge_pitch
        ).tts_config
        self._ssl = ssl.create_default_context(cafile=certifi.where())
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, name="edge-stream", daemon=True).start()
        self._session = None
        self._ws = None
        self._ws_lock = None  # created on self._loop

    # ---- connection (runs on self._loop) -----------------------------------

    async def _connect(self):
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
                # 403 usually means clock skew for the Sec-MS-GEC token.
                if exc.status != 403 or attempt == 2:
                    raise
                DRM.handle_client_response_error(exc)

    async def _ensure_ws(self):
        if self._ws_lock is None:
            self._ws_lock = asyncio.Lock()
        async with self._ws_lock:
            if self._ws is None or self._ws.closed:
                started = time.monotonic()
                self._ws = await self._connect()
                logger.bind(tag=TAG).debug(f"Edge connection ready in {time.monotonic() - started:.2f}s")
            return self._ws

    async def _drop_ws(self):
        ws, self._ws = self._ws, None
        if ws is not None and not ws.closed:
            await ws.close()

    async def _synthesize(self, text, out: queue.Queue):
        """Stream MP3 bytes of one request into out; None at the end, an exception on failure."""
        for attempt in (1, 2):
            got_audio = False
            try:
                ws = await self._ensure_ws()
                await ws.send_str(
                    f"X-Timestamp:{date_to_string()}\r\nContent-Type:application/json; charset=utf-8\r\n"
                    "Path:speech.config\r\n\r\n"
                    '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                    '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
                    f'"outputFormat":"{OUTPUT_FORMAT}"' "}}}}\r\n"
                )
                ssml = mkssml(self._tts_config, escape(remove_incompatible_characters(text)))
                await ws.send_str(ssml_headers_plus_data(connect_id(), date_to_string(), ssml))
                while True:
                    msg = await asyncio.wait_for(ws.receive(), CHUNK_TIMEOUT)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if "Path:turn.end" in msg.data:
                            out.put(None)
                            return
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        header_length = int.from_bytes(msg.data[:2], "big")
                        headers, data = get_headers_and_data(msg.data, header_length)
                        if headers.get(b"Path") == b"audio" and data:
                            got_audio = True
                            out.put(data)
                    else:
                        raise ConnectionError(f"Edge connection closed ({msg.type.name})")
            except Exception as exc:
                await self._drop_ws()
                if got_audio or attempt == 2:
                    out.put(exc)
                    return
                logger.bind(tag=TAG).warning(f"Edge request failed ({exc}); retrying on a new connection")

    # ---- xiaozhi TTS hooks (run on the TTS text thread) --------------------

    async def open_audio_channels(self, conn):
        await super().open_audio_channels(conn)
        asyncio.run_coroutine_threadsafe(self._warm_up(), self._loop)

    async def _warm_up(self):
        try:
            await self._ensure_ws()
        except Exception as exc:
            logger.bind(tag=TAG).warning(f"Edge warm-up failed: {exc}")

    def _get_segment_text(self):
        """First segment: up to the first punctuation mark (at least two characters)."""
        if not self.is_first_sentence:
            return super()._get_segment_text()
        current = "".join(self.tts_text_buff)[self.processed_chars:]
        end = next((i for i, ch in enumerate(current) if i >= 2 and ch in self.first_sentence_punctuations), None)
        if end is None:
            return super()._get_segment_text()
        raw = current[: end + 1]
        self.processed_chars += len(raw)
        self.is_first_sentence = False
        return textUtils.get_string_no_punctuation_or_emoji(raw)

    def to_tts_stream(self, text, opus_handler=None):
        original_text = text
        text = MarkdownCleaner.clean_markdown(text)
        if self._correct_words_pattern:
            text = self._correct_words_pattern.sub(lambda m: self.correct_words[m.group(0)], text)
        if not text.strip():
            return None
        sentence_id = getattr(self, "current_sentence_id", None)
        started = time.monotonic()
        chunks: queue.Queue = queue.Queue()
        asyncio.run_coroutine_threadsafe(self._synthesize(text, chunks), self._loop)

        decoder = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", *FFMPEG_INPUT, "-i", "pipe:0",
             "-f", "s16le", "-ac", "1", "-ar", str(self.conn.sample_rate), "-flush_packets", "1", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        state = {"first_audio": None}
        trimmer = SilenceTrimmer(self.conn.sample_rate)

        def send(pcm):
            if not pcm or self.conn.client_abort:
                return  # nothing to send / drain ffmpeg after an abort
            if state["first_audio"] is None:
                state["first_audio"] = time.monotonic() - started
                self.tts_audio_queue.put((SentenceType.FIRST, None, original_text, sentence_id))
            self.opus_encoder.encode_pcm_to_opus_stream(pcm, end_of_stream=False, callback=opus_handler)

        def pump_pcm():
            fd = decoder.stdout.fileno()
            while True:
                pcm = os.read(fd, 4096)
                if not pcm:
                    send(trimmer.finish())
                    return
                send(trimmer.push(pcm))

        reader = threading.Thread(target=pump_pcm, name="edge-stream-pcm", daemon=True)
        reader.start()
        error = None
        try:
            while True:
                item = chunks.get(timeout=CHUNK_TIMEOUT + 5)
                if item is None:
                    break
                if isinstance(item, Exception):
                    error = item
                    break
                decoder.stdin.write(item)
                decoder.stdin.flush()
        except queue.Empty:
            error = TimeoutError("no data from Edge")
        except (BrokenPipeError, OSError) as exc:
            error = exc
        finally:
            try:
                decoder.stdin.close()
            except OSError:
                pass
            reader.join(timeout=10)
            decoder.wait(timeout=5)

        if state["first_audio"] is not None:
            # Pad and send the last partial Opus frame of this segment.
            self.opus_encoder.encode_pcm_to_opus_stream(b"", end_of_stream=True, callback=opus_handler)
        if error is not None:
            if state["first_audio"] is None and not self.conn.client_abort:
                logger.bind(tag=TAG).warning(f"流式 Edge 失败，改用普通 Edge 重试: {original_text}，错误: {error}")
                return super().to_tts_stream(original_text, opus_handler)
            logger.bind(tag=TAG).error(f"流式 Edge 中途失败: {original_text}，错误: {error}")
            return None
        logger.bind(tag=TAG).info(
            f"语音生成成功(流式): {original_text}，首包 {state['first_audio'] or 0:.2f}s，"
            f"完成 {time.monotonic() - started:.2f}s"
        )
        return None

    async def close(self):
        await super().close()
        future = asyncio.run_coroutine_threadsafe(self._close_connection(), self._loop)
        try:
            await asyncio.wrap_future(future)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _close_connection(self):
        await self._drop_ws()
        if self._session is not None and not self._session.closed:
            await self._session.close()
