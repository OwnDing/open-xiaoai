"""The voice terminal: wake word → listen → server reply → play, one device, half duplex."""

import asyncio
import collections
import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .audio import read_wav, refresh_devices
from .codec import OpusDecoder, OpusEncoder
from .config import TerminalConfig
from .protocol import XiaozhiConnection

log = logging.getLogger(__name__)

RATE = 16000
PROMPT_RATE = 48000
# The backend is usually on the same LAN or host; after it restarts the
# terminal should be back within seconds.
RECONNECT_MAX_DELAY = 10.0
AUDIO_RETRY_SECONDS = 5.0


class Mode:
    OFF = "off"  # mic ignored (playing, waiting for the server)
    WAKE = "wake"  # wake-word detection
    WAIT_SPEECH = "wait_speech"  # awake, waiting for the user to start talking
    STREAM = "stream"  # uploading the utterance


class State:
    CONNECTING = "connecting"
    STANDBY = "standby"
    AWAKE = "awake"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class Event:
    kind: str
    data: object = None
    at: float = field(default_factory=time.monotonic)


class FrameRouter:
    """Runs on the mic thread; posts ("wake", word), ("speech_start", packets),
    ("audio", packets) and ("speech_end", None) to the event loop in order."""

    def __init__(self, wake, speech, encoder: OpusEncoder, pre_roll_ms: int, post):
        self._wake, self._speech, self._encoder = wake, speech, encoder
        self._post = post
        self._ring = collections.deque()
        self._ring_limit = int(pre_roll_ms * RATE / 1000)
        self._ring_size = 0
        self._lock = threading.Lock()
        self.mode = Mode.OFF

    def set_mode(self, mode: str):
        with self._lock:
            if mode == Mode.WAKE and self._wake is not None:
                self._wake.reset()
            elif mode == Mode.WAIT_SPEECH:
                self._speech.reset(in_utterance=False)
                self._ring.clear()
                self._ring_size = 0
            self.mode = mode

    def on_frame(self, frame: np.ndarray):
        with self._lock:
            if self.mode == Mode.WAKE:
                if self._wake is not None:
                    word = self._wake.accept(frame)
                    if word:
                        self.mode = Mode.OFF
                        self._post("wake", word)
            elif self.mode == Mode.WAIT_SPEECH:
                self._ring.append(frame)
                self._ring_size += len(frame)
                while self._ring_size - len(self._ring[0]) >= self._ring_limit:
                    self._ring_size -= len(self._ring.popleft())
                if "start" in self._speech.accept(frame):
                    self._encoder.reset()
                    packets = self._encoder.encode(np.concatenate(self._ring))
                    self._ring.clear()
                    self._ring_size = 0
                    self.mode = Mode.STREAM
                    self._post("speech_start", packets)
            elif self.mode == Mode.STREAM:
                events = self._speech.accept(frame)
                packets = self._encoder.encode(frame)
                if packets:
                    self._post("audio", packets)
                if "end" in events:
                    self.mode = Mode.OFF
                    self._post("speech_end", None)


def tone_prompt(freqs, seconds=0.12, gap=0.04, amplitude=0.3):
    parts = []
    for freq in freqs:
        t = np.arange(int(seconds * PROMPT_RATE)) / PROMPT_RATE
        y = amplitude * np.sin(2 * np.pi * freq * t)
        fade = int(0.01 * PROMPT_RATE)
        y[:fade] *= np.linspace(0, 1, fade)
        y[-fade:] *= np.linspace(1, 0, fade)
        parts += [y, np.zeros(int(gap * PROMPT_RATE))]
    return np.concatenate(parts).astype(np.float32)


DEFAULT_PROMPTS = {
    "wake": (660, 990),
    "no_reply": (440, 440),
    "goodbye": (990, 660),
}


class Terminal:
    def __init__(self, config: TerminalConfig, make_mic, speaker, wake_detector, speech_detector,
                 connection_factory=XiaozhiConnection):
        """make_mic(on_frame) builds the (real or file) microphone."""
        self.config = config
        self._make_mic = make_mic
        self._connection_factory = connection_factory
        self.speaker = speaker
        self.mic = None
        self.router = FrameRouter(wake_detector, speech_detector, OpusEncoder(), config.vad.pre_roll_ms, self._post_from_mic)
        self._decoder = OpusDecoder()
        self.conn: XiaozhiConnection | None = None
        self.state = State.CONNECTING
        self.loop: asyncio.AbstractEventLoop | None = None
        self._uplink: asyncio.Queue = asyncio.Queue()
        self._events: asyncio.Queue = asyncio.Queue()
        self._dialog: asyncio.Task | None = None
        self._accept_audio = False
        self._audio_ok = False
        self._prompts = self._load_prompts()
        self.stats = {"turns": 0, "last_stt": "", "last_reply": "", "last_turn": {}, "reconnects": 0}
        self._turn = {}
        self._stopping = asyncio.Event()

    # ---- setup -------------------------------------------------------------

    def _load_prompts(self):
        session = self.config.session
        prompts = {}
        for name, freqs in DEFAULT_PROMPTS.items():
            path = getattr(session, f"{name}_prompt")
            if path:
                samples, rate = read_wav(self.config.path(path))
                prompts[name] = (samples, rate)
            else:
                prompts[name] = (tone_prompt(freqs), PROMPT_RATE)
        return prompts

    def _post_from_mic(self, kind, data):
        self.loop.call_soon_threadsafe(self._uplink.put_nowait, Event(kind, data))

    def _start_audio(self) -> bool:
        try:
            self.speaker.start()
            self.mic = self._make_mic(self.router.on_frame)
            self.mic.start()
            self._audio_ok = True
            return True
        except Exception as exc:
            log.warning("audio devices unavailable: %s", exc)
            self._stop_audio()
            return False

    def _stop_audio(self):
        if self.mic is not None:
            self.mic.stop()
            self.mic = None
        self.speaker.stop()
        self._audio_ok = False

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self._start_audio()
        tasks = [
            asyncio.create_task(self._uplink_loop(), name="uplink"),
            asyncio.create_task(self._connection_loop(), name="connection"),
            asyncio.create_task(self._audio_health_loop(), name="audio-health"),
        ]
        try:
            await self._stopping.wait()
        finally:
            await self.stop_dialog(notify_server=False)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.conn is not None:
                await self.conn.close()
            self._stop_audio()

    def shutdown(self):
        self._stopping.set()

    async def _audio_health_loop(self):
        while True:
            await asyncio.sleep(AUDIO_RETRY_SECONDS if not self._audio_ok else 1.0)
            if self._audio_ok and not (self.mic is not None and self.mic.stalled):
                continue
            if self._audio_ok:
                log.warning("microphone stalled; reopening audio devices")
                await self.stop_dialog(notify_server=True)
            self._stop_audio()
            try:
                refresh_devices()
            except Exception:
                pass
            if self._start_audio():
                log.info("audio devices reopened")
                if self._dialog is None:
                    self.router.set_mode(Mode.WAKE)

    async def _connection_loop(self):
        delay = 1.0
        while True:
            conn = self._connection_factory(
                self.config.server.websocket_url, self.config.device_id, self.config.client_id,
                self.config.server.access_token, self._on_json, self._on_audio,
            )
            try:
                await conn.connect()
            except Exception as exc:
                log.warning("connect failed: %s; retry in %.0f s", exc, delay)
                await conn.close()
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                continue
            delay = 1.0
            self.conn = conn
            if self._dialog is None:
                self.state = State.STANDBY
                self.router.set_mode(Mode.WAKE)
            await conn.closed.wait()
            self.conn = None
            self.stats["reconnects"] += 1
            if self._dialog is not None:
                log.warning("connection lost during a conversation; back to standby")
                await self.stop_dialog(notify_server=False)
            self.state = State.CONNECTING

    # ---- mic → server ------------------------------------------------------

    async def _uplink_loop(self):
        while True:
            event = await self._uplink.get()
            try:
                if event.kind == "wake":
                    log.info("wake word: %s", event.data)
                    if self._dialog is None and self.conn is not None:
                        self.start_dialog("wake")
                    else:
                        self.router.set_mode(Mode.WAKE if self._dialog is None else self.router.mode)
                    continue
                if self.conn is None:
                    continue
                if event.kind == "speech_start":
                    await self.conn.listen_start("manual")
                    for packet in event.data:
                        await self.conn.send_audio(packet)
                    self._events.put_nowait(event)
                elif event.kind == "audio":
                    for packet in event.data:
                        await self.conn.send_audio(packet)
                elif event.kind == "speech_end":
                    await self.conn.listen_stop()
                    self._events.put_nowait(event)
            except ConnectionError:
                pass
            except Exception:
                log.exception("uplink failed for %s", event.kind)

    # ---- server → terminal ---------------------------------------------------

    def _on_json(self, data: dict):
        kind = data.get("type")
        if kind == "stt":
            text = data.get("text", "")
            log.info("user: %s", text)
            self.stats["last_stt"] = text
            self._events.put_nowait(Event("stt", text))
        elif kind == "tts":
            state = data.get("state")
            if state == "start":
                self._decoder.reset()
                self._accept_audio = True
                self.stats["last_reply"] = ""
                if self._dialog is None:
                    self.start_dialog("server")
                self._events.put_nowait(Event("tts_start"))
            elif state == "sentence_start":
                text = data.get("text", "")
                if text:
                    log.info("reply: %s", text)
                    self.stats["last_reply"] += text
            elif state == "stop":
                self._events.put_nowait(Event("tts_stop"))
        elif kind not in ("llm", "pong"):
            log.debug("server message: %s", data)

    def _on_audio(self, packet: bytes):
        if not self._accept_audio:
            return
        if "first_audio" not in self._turn:
            self._turn["first_audio"] = time.monotonic()
        try:
            self.speaker.feed(self._decoder.decode(packet))
        except Exception:
            log.exception("decoding server audio failed")

    # ---- conversation ------------------------------------------------------

    def start_dialog(self, trigger: str, text: str = ""):
        previous = self._dialog
        self._dialog = asyncio.create_task(self._dialog_run(trigger, text, previous), name=f"dialog-{trigger}")

    async def stop_dialog(self, notify_server: bool = True):
        task, self._dialog = self._dialog, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._accept_audio = False
        self.speaker.flush()
        if notify_server and self.conn is not None:
            try:
                await self.conn.abort()
            except ConnectionError:
                pass
        self.state = State.STANDBY if self.conn is not None else State.CONNECTING
        self.router.set_mode(Mode.WAKE)

    async def _wait(self, kinds, timeout):
        """Next event of the given kinds; None on timeout. Other events are dropped."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                event = await asyncio.wait_for(self._events.get(), remaining)
            except asyncio.TimeoutError:
                return None
            if event.kind in kinds:
                return event
            log.debug("ignored %s while waiting for %s", event.kind, kinds)

    def _drain_events(self):
        while not self._events.empty():
            self._events.get_nowait()

    async def _play_prompt(self, name):
        self.router.set_mode(Mode.OFF)
        samples, rate = self._prompts[name]
        self.speaker.play(samples, rate)
        await self.speaker.drained()
        await asyncio.sleep(self.config.session.tts_end_guard_ms / 1000)

    async def _dialog_run(self, trigger, text, previous):
        if previous is not None and not previous.done():
            previous.cancel()
            await asyncio.gather(previous, return_exceptions=True)
        session = self.config.session
        me = asyncio.current_task()
        try:
            self.router.set_mode(Mode.OFF)
            if trigger != "server":
                self._drain_events()
                self._accept_audio = False
                self.speaker.flush()
            if trigger in ("wake", "manual"):
                await self._play_prompt("wake")
            if trigger == "text":
                if self.conn is None:
                    log.warning("not connected; dropped text request")
                    return
                self._turn = {"speech_end": time.monotonic()}
                self.state = State.THINKING
                await self.conn.listen_detect(text)
                await self._await_reply()
            elif trigger == "server":
                self._turn = {"speech_end": time.monotonic()}
                await self._await_reply(started=True)
            while True:
                self.state = State.AWAKE
                self.router.set_mode(Mode.WAIT_SPEECH)
                event = await self._wait({"speech_start", "tts_start"}, session.idle_timeout_s)
                if event is None:
                    log.info("no speech for %.0f s; standby", session.idle_timeout_s)
                    await self._play_prompt("goodbye")
                    break
                if event.kind == "tts_start":
                    # A late answer arrived before the user spoke again: play it.
                    self.router.set_mode(Mode.OFF)
                    self._turn = {"speech_end": event.at}
                    await self._await_reply(started=True)
                    continue
                self.state = State.LISTENING
                if await self._wait({"speech_end"}, self.config.vad.max_utterance_s + 5) is None:
                    log.warning("utterance did not end; standby")
                    break
                self._turn = {"speech_end": time.monotonic()}
                self.state = State.THINKING
                if await self._await_reply() == "no_reply":
                    await self._play_prompt("no_reply")
        finally:
            self._accept_audio = False
            if self._dialog is me:
                self._dialog = None
                self.state = State.STANDBY if self.conn is not None else State.CONNECTING
                self.router.set_mode(Mode.WAKE)

    async def _await_reply(self, started=False) -> str:
        session = self.config.session
        if not started:
            event = await self._wait({"stt", "tts_start"}, session.no_reply_timeout_s)
            if event is None:
                log.info("no recognition result")
                return "no_reply"
            if event.kind == "stt":
                self._turn["stt"] = event.at
                if await self._wait({"tts_start"}, session.reply_timeout_s) is None:
                    log.warning("no reply within %.0f s", session.reply_timeout_s)
                    return "timeout"
        self._turn["tts_start"] = time.monotonic()
        self.state = State.SPEAKING
        stopped = await self._wait({"tts_stop"}, session.reply_timeout_s)
        self.speaker.end_stream()
        await self.speaker.drained()
        self._turn["played"] = time.monotonic()
        self._record_turn()
        await asyncio.sleep(session.tts_end_guard_ms / 1000)
        return "answered" if stopped else "timeout"

    def _record_turn(self):
        start = self._turn.get("speech_end")
        if start is None:
            return
        self.stats["turns"] += 1
        self.stats["last_turn"] = {
            key: round(value - start, 3) for key, value in self._turn.items() if key != "speech_end"
        }
        log.info("turn timings (s after speech end): %s", self.stats["last_turn"])

    def status(self) -> dict:
        return {
            "name": self.config.name,
            "device_id": self.config.device_id,
            "state": self.state,
            "mode": self.router.mode,
            "connected": self.conn is not None and self.conn.is_open,
            "audio_ok": self._audio_ok,
            "mic": getattr(self.mic, "name", ""),
            "speaker": self.speaker.name,
            **self.stats,
        }
