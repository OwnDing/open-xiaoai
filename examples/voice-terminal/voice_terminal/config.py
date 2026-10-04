"""Terminal configuration, loaded from a TOML file."""

import tomllib
import uuid
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class ServerConfig:
    websocket_url: str = "ws://127.0.0.1:18000/xiaozhi/v1/"
    access_token: str = ""


@dataclass
class AudioConfig:
    # Device names as the audio API reports them; an exact name wins over a substring.
    input: str = ""
    output: str = ""
    # Substring of the PortAudio host API name ("WASAPI" on Windows, "" for any).
    host_api: str = "WASAPI"
    # Front-end stages on the 16 kHz mic signal: "hpf", "ns", "agc".
    frontend: list[str] = field(default_factory=lambda: ["hpf", "ns", "agc"])
    output_gain: float = 1.0


@dataclass
class WakeConfig:
    keywords: list[str] = field(default_factory=lambda: ["你好小七"])
    model_dir: str = "models/kws"
    threshold: float = 0.2
    score: float = 2.0


@dataclass
class VadConfig:
    model: str = "models/silero_vad.onnx"
    threshold: float = 0.5
    min_speech_ms: int = 250
    min_silence_ms: int = 500
    # A very short utterance ("啊", "嗯") waits longer before the turn ends.
    short_utterance_ms: int = 800
    short_utterance_silence_ms: int = 1000
    pre_roll_ms: int = 800
    max_utterance_s: float = 15.0


@dataclass
class SessionConfig:
    # No speech for this long after waking or after a reply: back to standby.
    idle_timeout_s: float = 20.0
    # Keep the mic closed this long after playback ends (speaker echo tail).
    tts_end_guard_ms: int = 400
    # No recognition result this long after the user stopped talking: ask again.
    no_reply_timeout_s: float = 6.0
    # Recognized, but no answer started this long after: give up on this turn.
    reply_timeout_s: float = 90.0
    # Prompt WAVs (any rate, mono or stereo); empty uses a built-in tone.
    wake_prompt: str = ""
    no_reply_prompt: str = ""
    goodbye_prompt: str = ""


@dataclass
class ControlConfig:
    host: str = "127.0.0.1"
    # 0 disables the local control API.
    port: int = 18110


@dataclass
class TerminalConfig:
    name: str = "voice-terminal"
    device_id: str = ""
    client_id: str = ""
    room: str = ""
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    base_dir: Path = Path(".")

    def path(self, value: str) -> Path:
        """Resolve a path from the config relative to the config file."""
        p = Path(value)
        return p if p.is_absolute() else self.base_dir / p


SECTIONS = {
    "server": ServerConfig,
    "audio": AudioConfig,
    "wake": WakeConfig,
    "vad": VadConfig,
    "session": SessionConfig,
    "control": ControlConfig,
}


def _build(cls, values: dict, where: str):
    known = {f.name for f in fields(cls)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"unknown option(s) in [{where}]: {', '.join(sorted(unknown))}")
    return cls(**values)


def load_config(path: str | Path) -> TerminalConfig:
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    terminal = dict(data.pop("terminal", {}))
    sections = {name: _build(cls, data.pop(name, {}), name) for name, cls in SECTIONS.items()}
    if data:
        raise ValueError(f"unknown section(s): {', '.join(sorted(data))}")
    config = _build(TerminalConfig, {**terminal, **sections}, "terminal")
    config.base_dir = path.parent.resolve()
    if not config.device_id:
        raise ValueError("[terminal] device_id is required (e.g. 02:76:74:00:00:01)")
    if not config.client_id:
        config.client_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"open-xiaoai-voice-terminal:{config.device_id}"))
    unknown_stages = set(config.audio.frontend) - {"hpf", "ns", "agc"}
    if unknown_stages:
        raise ValueError(f"unknown [audio] frontend stage(s): {', '.join(sorted(unknown_stages))}")
    return config
