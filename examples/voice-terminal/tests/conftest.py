import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_terminal.config import SessionConfig, TerminalConfig, VadConfig  # noqa: E402


class FakeConnection:
    instances: list["FakeConnection"] = []

    def __init__(self, url, device_id, client_id, token, on_json, on_audio):
        self.device_id = device_id
        self.on_json, self.on_audio = on_json, on_audio
        self.sent = []
        self.closed = asyncio.Event()
        self.session_id = ""
        FakeConnection.instances.append(self)

    async def connect(self):
        self.session_id = f"s{len(FakeConnection.instances)}"

    @property
    def is_open(self):
        return not self.closed.is_set()

    async def send_audio(self, packet):
        self.sent.append(packet)

    async def listen_start(self, mode="manual"):
        self.sent.append(("listen", "start", mode))

    async def listen_stop(self):
        self.sent.append(("listen", "stop"))

    async def listen_detect(self, text):
        self.sent.append(("listen", "detect", text))

    async def abort(self):
        self.sent.append(("abort",))

    async def close(self):
        self.closed.set()


class FakeSpeaker:
    name = "fake-speaker"

    def __init__(self):
        self.played = []  # prompt clips
        self.fed = 0  # server audio samples
        self.flushes = 0
        self.ended = 0

    def start(self):
        pass

    def stop(self):
        pass

    def feed(self, pcm):
        self.fed += len(pcm)

    def end_stream(self):
        self.ended += 1

    def play(self, samples, rate):
        self.played.append(len(samples) / rate)

    def flush(self):
        self.flushes += 1

    busy = False

    async def drained(self):
        await asyncio.sleep(0)


class FakeMic:
    name = "fake-mic"
    stalled = False

    def start(self):
        pass

    def stop(self):
        pass


@pytest.fixture
def config(tmp_path):
    return TerminalConfig(
        base_dir=tmp_path,
        name="test",
        device_id="02:76:74:00:00:99",
        client_id="test-client",
        vad=VadConfig(max_utterance_s=1.0),
        session=SessionConfig(idle_timeout_s=0.3, tts_end_guard_ms=10, no_reply_timeout_s=0.2, reply_timeout_s=1.0),
    )


async def wait_for(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)
