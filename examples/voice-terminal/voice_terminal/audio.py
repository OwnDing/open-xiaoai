"""Audio devices: mic capture to 16 kHz frames, speaker playback, WAV stand-ins for tests."""

import asyncio
import collections
import logging
import queue
import threading
import time
import wave
from pathlib import Path

import numpy as np
import soxr

from .frontend import FRAME, RATE, Frontend

log = logging.getLogger(__name__)

# Server TTS is decoded to this rate before it reaches the speaker.
PLAYBACK_SOURCE_RATE = 48000
STALL_SECONDS = 3.0


def _sd():
    import sounddevice

    return sounddevice


def list_devices(host_api: str = ""):
    sd = _sd()
    rows = []
    for index, dev in enumerate(sd.query_devices()):
        api = sd.query_hostapis(dev["hostapi"])["name"]
        if host_api and host_api.lower() not in api.lower():
            continue
        rows.append((index, api, dev["max_input_channels"], dev["max_output_channels"], dev["default_samplerate"], dev["name"]))
    return rows


def find_device(spec: str, kind: str, host_api: str = "") -> int:
    """Device index by exact name, then unique substring, within host_api."""
    key = 2 if kind == "input" else 3
    rows = [row for row in list_devices(host_api) if row[key] > 0]
    for matches in ([r for r in rows if r[5] == spec], [r for r in rows if spec in r[5]]):
        if len(matches) == 1:
            return matches[0][0]
        if matches:
            names = ", ".join(f"[{r[0]}] {r[5]}" for r in matches)
            raise LookupError(f"{kind} device {spec!r} is ambiguous: {names}")
    names = ", ".join(f"[{r[0]}] {r[5]}" for r in rows) or "none"
    raise LookupError(f"{kind} device {spec!r} not found; available: {names}")


def refresh_devices():
    """Re-scan devices (PortAudio caches the list). All streams must be closed."""
    sd = _sd()
    sd._terminate()
    sd._initialize()


def read_wav(path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: only 16-bit PCM WAV is supported")
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return (data.reshape(-1, channels).mean(axis=1) / 32768.0).astype(np.float32), rate


def read_audio(path) -> tuple[np.ndarray, int]:
    """Mono float32 samples and rate from a 16-bit WAV or anything FFmpeg decodes (MP3, ...)."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        return read_wav(path)
    import av

    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate = stream.rate
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        chunks = []
        for frame in container.decode(stream):
            chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    return (np.concatenate(chunks) if chunks else np.zeros(0)).astype(np.float32), rate


def trim_silence(samples: np.ndarray, rate: int, lead_ms: int = 30, tail_ms: int = 120,
                 level_db: float = -45.0) -> np.ndarray:
    """Cut leading/trailing silence (Edge pads prompts with ~0.2 s before and ~0.6 s after)."""
    n = max(1, rate // 100)
    frames = len(samples) // n
    if frames == 0:
        return samples
    rms = np.sqrt(np.mean(samples[: frames * n].reshape(-1, n) ** 2, axis=1))
    loud = np.flatnonzero(20 * np.log10(np.maximum(rms, 1e-9)) > level_db)
    if not len(loud):
        return samples
    start = max(0, int(loud[0]) * n - rate * lead_ms // 1000)
    end = min(len(samples), (int(loud[-1]) + 1) * n + rate * tail_ms // 1000)
    return samples[start:end]


def write_wav(path, samples: np.ndarray, rate: int):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())


class _FrameCutter:
    """Resample any-rate mono float32 chunks to 16 kHz and cut 10 ms frames through the front end."""

    def __init__(self, in_rate: int, frontend: Frontend, on_frame):
        self._resampler = None if in_rate == RATE else soxr.ResampleStream(in_rate, RATE, 1, dtype="float32", quality="HQ")
        self._frontend = frontend
        self._on_frame = on_frame
        self._pending = np.zeros(0, dtype=np.float32)

    def push(self, chunk: np.ndarray):
        if self._resampler is not None:
            chunk = self._resampler.resample_chunk(chunk)
        self._pending = np.concatenate([self._pending, chunk]) if len(self._pending) else chunk
        count = len(self._pending) // FRAME
        for i in range(count):
            self._on_frame(self._frontend.process(self._pending[i * FRAME:(i + 1) * FRAME]))
        self._pending = self._pending[count * FRAME:]


class Microphone:
    """Captures one input device and calls on_frame(float32[160]) from a worker thread."""

    def __init__(self, spec: str, host_api: str, frontend: Frontend, on_frame):
        self.spec, self.host_api = spec, host_api
        self._frontend, self._on_frame = frontend, on_frame
        self._queue: queue.Queue = queue.Queue(maxsize=500)
        self._stream = None
        self._worker = None
        self._running = False
        self.name = ""
        self.rate = 0
        self.overflows = 0
        self.dropped = 0
        self.last_callback = 0.0
        self.started_at = time.monotonic()
        self.callback_samples = 0
        self.processed_samples = 0
        self.worker_errors = 0
        self.queue_peak = 0
        self.max_callback_gap_ms = 0.0
        self.max_queue_age_ms = 0.0

    def start(self):
        sd = _sd()
        index = find_device(self.spec, "input", self.host_api)
        dev = sd.query_devices(index)
        self.name, self.rate = dev["name"], int(dev["default_samplerate"])
        cutter = _FrameCutter(self.rate, self._frontend, self._on_frame)
        self._running = True
        self._worker = threading.Thread(target=self._work, args=(cutter,), name="mic-worker", daemon=True)
        self._worker.start()
        self._stream = sd.InputStream(
            device=index, samplerate=self.rate, channels=1, dtype="float32",
            callback=self._callback, latency="high",
        )
        self._stream.start()
        self.last_callback = time.monotonic()
        log.info("mic [%d] %s @ %d Hz", index, self.name, self.rate)

    def _callback(self, indata, frames, _time, status):
        now = time.monotonic()
        if self.last_callback:
            self.max_callback_gap_ms = max(self.max_callback_gap_ms, (now-self.last_callback)*1000)
        self.last_callback = now
        self.callback_samples += frames
        if status.input_overflow:
            self.overflows += 1
        try:
            self._queue.put_nowait((now, indata[:, 0].copy()))
            self.queue_peak = max(self.queue_peak, self._queue.qsize())
        except queue.Full:
            self.dropped += frames

    def _work(self, cutter):
        while self._running:
            try:
                captured_at, chunk = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.max_queue_age_ms = max(self.max_queue_age_ms, (time.monotonic()-captured_at)*1000)
                cutter.push(chunk)
                self.processed_samples += len(chunk)
            except Exception:
                self.worker_errors += 1
                log.exception("mic frame processing failed")

    def health(self):
        return {"mic_rate_hz": self.rate, "mic": self.name,
                "mic_callback_samples_total": self.callback_samples,
                "mic_processed_samples_total": self.processed_samples,
                "mic_overflows_total": self.overflows, "mic_dropped_samples_total": self.dropped,
                "mic_worker_errors_total": self.worker_errors,
                "mic_callback_age_ms": (time.monotonic()-self.last_callback)*1000 if self.last_callback else None,
                "mic_worker_alive": bool(self._worker and self._worker.is_alive()),
                "mic_queue_chunks": self._queue.qsize(), "mic_queue_peak_chunks": self.queue_peak,
                "mic_max_queue_age_ms": self.max_queue_age_ms, "mic_max_callback_gap_ms": self.max_callback_gap_ms}

    @property
    def stalled(self) -> bool:
        return self._running and time.monotonic() - self.last_callback > STALL_SECONDS

    def stop(self):
        self._running = False
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._worker is not None:
            self._worker.join(timeout=1)
            self._worker = None


class _PlaybackBuffer:
    """Jitter buffer between network audio and the device callback.

    The server paces TTS packets in real time, and after a pause between
    sentences each packet arrives just as it is due. Playing them one by one
    then runs dry dozens of times per second (heard as crackle), so whenever
    the buffer is empty it waits until `threshold` samples are queued before
    playing again. A clip marked complete (prompts, end of an answer) plays
    out without waiting.
    """

    def __init__(self, threshold: int = 0):
        self._chunks = collections.deque()
        self._lock = threading.Lock()
        self.threshold = threshold
        self.buffered = 0
        self.last_handoff = 0.0
        self.underruns = 0
        self._waiting = True  # refilling: output silence until threshold
        self._complete = False  # no more audio coming for the current clip

    def push(self, samples: np.ndarray, complete: bool = False):
        with self._lock:
            if len(samples):
                self._chunks.append(samples)
                self.buffered += len(samples)
            if complete:
                self._complete = True

    def mark_complete(self):
        with self._lock:
            self._complete = True

    def pull(self, count: int) -> np.ndarray:
        out = np.zeros(count, dtype=np.float32)
        filled = 0
        with self._lock:
            if self._waiting and (self.buffered >= self.threshold or (self._complete and self.buffered)):
                self._waiting = False
            if not self._waiting:
                while filled < count and self._chunks:
                    chunk = self._chunks[0]
                    take = min(count - filled, len(chunk))
                    out[filled:filled + take] = chunk[:take]
                    filled += take
                    if take == len(chunk):
                        self._chunks.popleft()
                    else:
                        self._chunks[0] = chunk[take:]
                self.buffered -= filled
                if self.buffered == 0:
                    if not self._complete:
                        self.underruns += 1
                    # Refill before playing whatever comes next.
                    self._waiting = True
                    self._complete = False
        if filled:
            self.last_handoff = time.monotonic()
        return out

    def clear(self):
        with self._lock:
            self._chunks.clear()
            self.buffered = 0
            self._waiting = True
            self._complete = False


class Speaker:
    """Persistent output stream fed with 48 kHz mono float32 PCM."""

    def __init__(self, spec: str, host_api: str, gain: float = 1.0, buffer_ms: int = 240):
        self.spec, self.host_api, self.gain = spec, host_api, gain
        self.buffer_ms = buffer_ms
        self._buffer = _PlaybackBuffer()
        self._stream = None
        self._resampler = None
        self.name = ""
        self.rate = 0
        self.channels = 0
        self.latency = 0.0

    def start(self):
        sd = _sd()
        index = find_device(self.spec, "output", self.host_api)
        dev = sd.query_devices(index)
        self.name, self.rate = dev["name"], int(dev["default_samplerate"])
        self.channels = min(2, dev["max_output_channels"])
        self._buffer.threshold = int(self.buffer_ms * self.rate / 1000)
        self._resampler = soxr.ResampleStream(PLAYBACK_SOURCE_RATE, self.rate, 1, dtype="float32", quality="HQ")
        self._stream = sd.OutputStream(
            device=index, samplerate=self.rate, channels=self.channels, dtype="float32",
            callback=self._callback, latency="high",
        )
        self._stream.start()
        self.latency = float(self._stream.latency)
        log.info("speaker [%d] %s @ %d Hz, latency %.0f ms", index, self.name, self.rate, self.latency * 1000)

    def _callback(self, outdata, frames, _time, _status):
        outdata[:] = self._buffer.pull(frames)[:, None]

    def feed(self, pcm48: np.ndarray):
        """Stream decoded server audio (48 kHz)."""
        self._buffer.push(self._resampler.resample_chunk(pcm48 * self.gain))

    def end_stream(self):
        """No more audio for this answer: play out what is buffered."""
        tail = self._resampler.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
        self._buffer.push(tail, complete=True)
        self._resampler.clear()

    def play(self, samples: np.ndarray, rate: int):
        """Queue a complete clip (prompt) at any rate."""
        self._buffer.push(soxr.resample(samples * self.gain, rate, self.rate).astype(np.float32), complete=True)

    @property
    def underruns(self) -> int:
        return self._buffer.underruns

    def flush(self):
        self._buffer.clear()
        if self._resampler is not None:
            self._resampler.clear()

    @property
    def busy(self) -> bool:
        return self._buffer.buffered > 0

    async def drained(self):
        """Wait until everything queued has left the device buffer."""
        while self._buffer.buffered > 0:
            await asyncio.sleep(0.02)
        remaining = self._buffer.last_handoff + self.latency - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


class FileMicrophone:
    """Test stand-in: plays WAV clips into the pipeline in real time, silence in between.

    script: list of (start_seconds, path); start is relative to start().
    """

    def __init__(self, script, frontend: Frontend, on_frame, noise_dbfs: float = -70.0):
        self._script = sorted((float(at), Path(path)) for at, path in script)
        self._frontend, self._on_frame = frontend, on_frame
        self._noise = 10 ** (noise_dbfs / 20)
        self._running = False
        self._thread = None
        self.name, self.rate = "file", RATE
        self.overflows = self.dropped = 0
        self.stalled = False

    def start(self):
        clips = []
        for at, path in self._script:
            samples, rate = read_audio(path)
            clips.append((at, soxr.resample(samples, rate, RATE).astype(np.float32) if rate != RATE else samples))
        self._running = True
        self._thread = threading.Thread(target=self._run, args=(clips,), name="file-mic", daemon=True)
        self._thread.start()

    def _run(self, clips):
        rng = np.random.default_rng(0)
        cutter = _FrameCutter(RATE, self._frontend, self._on_frame)
        t0 = time.monotonic()
        sent = 0
        pending = collections.deque(clips)
        current = None
        while self._running:
            elapsed = time.monotonic() - t0
            due = int(elapsed * RATE) - sent
            if due < FRAME:
                time.sleep(0.005)
                continue
            due -= due % FRAME
            chunk = (rng.standard_normal(due) * self._noise).astype(np.float32)
            if current is None and pending and elapsed >= pending[0][0]:
                current = [pending.popleft()[1], 0]
            if current is not None:
                clip, pos = current
                take = min(due, len(clip) - pos)
                chunk[:take] += clip[pos:pos + take]
                current[1] += take
                if current[1] >= len(clip):
                    current = None
            cutter.push(chunk)
            sent += due

    def stop(self):
        self._running = False


class FileSpeaker:
    """Test stand-in: records everything played to a 48 kHz WAV, drains in real time."""

    def __init__(self, path):
        self.path = Path(path)
        self.rate = PLAYBACK_SOURCE_RATE
        self.name = f"file:{self.path.name}"
        self.latency = 0.0
        self._recorded = []
        self._busy_until = 0.0

    def start(self):
        pass

    def _account(self, count):
        now = time.monotonic()
        self._busy_until = max(now, self._busy_until) + count / self.rate

    def feed(self, pcm48):
        self._recorded.append(pcm48.astype(np.float32))
        self._account(len(pcm48))

    def end_stream(self):
        pass

    def play(self, samples, rate):
        clip = soxr.resample(samples, rate, self.rate).astype(np.float32) if rate != self.rate else samples
        self.feed(clip)

    def flush(self):
        self._busy_until = time.monotonic()

    @property
    def busy(self):
        return time.monotonic() < self._busy_until

    async def drained(self):
        remaining = self._busy_until - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)

    def stop(self):
        if self._recorded:
            write_wav(self.path, np.concatenate(self._recorded), self.rate)

    @property
    def recorded_seconds(self) -> float:
        return sum(len(c) for c in self._recorded) / self.rate
