"""Configuration loader compatible with xiaozhi-server's data/.config.yaml.

Reads the existing xiaozhi data/.config.yaml directly (or a slim gateway YAML)
so no secrets or device mappings need to be duplicated during migration.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("voice-gateway.config")

REPLY_STYLES = {
    "sentence": "用完整的一句话回答，不要只说一个字或一个词。",
}

# Upstream xiaozhi-esp32-server merges default TTS entries from its built-in
# config.yaml. Providing the same minimal defaults lets voice_devices entries
# such as `tts: EdgeTTS` work even when only EdgeStreamTTS/SherpaOnnxTTS appear
# in data/.config.yaml.
BUILTIN_TTS_DEFAULTS: dict[str, dict[str, Any]] = {
    "EdgeTTS": {
        "type": "edge",
        "voice": "zh-CN-XiaoxiaoNeural",
    },
    "EdgeStreamTTS": {
        "type": "edge_stream",
        "voice": "zh-CN-XiaoxiaoNeural",
    },
    "SherpaOnnxTTS": {
        "type": "index_stream",
        "api_url": "http://sherpa-tts:11996/tts",
        "voice": "xiao_ya",
        "audio_format": "pcm",
    },
}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


@dataclass(frozen=True)
class DeviceProfile:
    device_id: str
    server_audio: bool
    tts_name: str
    tts_config: dict[str, Any]
    room: str
    reply_style: str
    send_interval_ms: int


class GatewayConfig:
    """Normalized view over data/.config.yaml + environment overrides."""

    def __init__(self, raw: dict[str, Any], base_dir: Path | None = None):
        self.raw = raw or {}
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.ws_host = os.getenv("GATEWAY_WS_HOST", "0.0.0.0")
        self.ws_port = _env_int("GATEWAY_WS_PORT", 8000)
        self.http_host = os.getenv("GATEWAY_HTTP_HOST", "0.0.0.0")
        self.http_port = _env_int("GATEWAY_HTTP_PORT", 8003)
        self.output_mode = os.getenv("XIAOZHI_TTS_OUTPUT_MODE", "native_xiaomi").strip().lower()
        self.server_audio_env = {
            _norm(d) for d in os.getenv("XIAOZHI_SERVER_AUDIO_DEVICES", "").split(",") if d.strip()
        }
        self.history_max_messages = _env_int("GATEWAY_HISTORY_MESSAGES", 12)
        self.history_idle_reset_s = _env_float("GATEWAY_HISTORY_IDLE_RESET_S", 600.0)
        self.max_audio_s = _env_float("GATEWAY_MAX_AUDIO_S", 30.0)
        self.asr_threads = _env_int("GATEWAY_ASR_THREADS", 2)
        self.default_send_interval_ms = _env_int(
            "GATEWAY_SEND_INTERVAL_MS",
            int(self.raw.get("tts_audio_send_delay") or 60),
        )
        self.announce_token = os.getenv("GATEWAY_ANNOUNCE_TOKEN", "").strip()
        self.health_log_path = Path(
            os.getenv("GATEWAY_HEALTH_LOG", str(self.base_dir / "data" / "audio-health.jsonl"))
        )
        self.hermes_provider_dir = Path(
            os.getenv("HERMES_PROVIDER_DIR", str(self.base_dir / "hermes-provider"))
        )
        self.home_rules_dir = Path(
            os.getenv("HOME_RULES_DIR", str(self.base_dir / "home-rules"))
        )

    @classmethod
    def from_file(cls, path: str | Path, base_dir: Path | None = None) -> "GatewayConfig":
        cfg_path = Path(path)
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Expected YAML mapping in {cfg_path}")
        if base_dir is None:
            # data/.config.yaml sits under <root>/data/.config.yaml
            base_dir = cfg_path.parent.parent if cfg_path.parent.name == "data" else cfg_path.parent
        return cls(raw, base_dir=base_dir)

    def resolve_path(self, path_str: str) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p
        return (self.base_dir / p).resolve()

    # ---- modules -----------------------------------------------------------

    @property
    def selected(self) -> dict[str, str]:
        return self.raw.get("selected_module") or {}

    @property
    def asr_config(self) -> dict[str, Any]:
        asr_map = self.raw.get("ASR") or {}
        selected_name = self.selected.get("ASR")
        cfg = dict(asr_map.get(selected_name) or {}) if selected_name else {}
        if not cfg:
            # Prefer a sherpa_onnx_local entry if selected_module wasn't set.
            for entry in asr_map.values():
                if isinstance(entry, dict) and entry.get("type") == "sherpa_onnx_local":
                    cfg = dict(entry)
                    break
        model_dir = os.getenv("GATEWAY_ASR_MODEL_DIR") or cfg.get("model_dir") or "models/sherpa-onnx-sense-voice"
        cfg["model_dir"] = str(self.resolve_path(str(model_dir)))
        cfg.setdefault("num_threads", self.asr_threads)
        cfg.setdefault("max_audio_s", self.max_audio_s)
        return cfg

    @property
    def llm_config(self) -> dict[str, Any]:
        llm_map = self.raw.get("LLM") or {}
        selected_name = self.selected.get("LLM")
        if selected_name and isinstance(llm_map.get(selected_name), dict):
            return dict(llm_map[selected_name])
        for entry in llm_map.values():
            if isinstance(entry, dict) and entry.get("type") == "hermes":
                return dict(entry)
        return {}

    @property
    def tts_modules(self) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {k: dict(v) for k, v in BUILTIN_TTS_DEFAULTS.items()}
        for name, entry in (self.raw.get("TTS") or {}).items():
            if isinstance(entry, dict):
                base = dict(merged.get(name) or {})
                base.update(entry)
                merged[name] = base
        return merged

    @property
    def default_tts_name(self) -> str:
        return str(self.selected.get("TTS") or "SherpaOnnxTTS")

    @property
    def fallback_sherpa_config(self) -> dict[str, Any] | None:
        """Offline Sherpa TTS config used as fallback when network TTS fails."""
        modules = self.tts_modules
        for name, cfg in modules.items():
            t = _norm(cfg.get("type"))
            if t in ("index_stream", "sherpa", "sherpa_local") and (cfg.get("api_url") or cfg.get("model_dir")):
                return dict(cfg)
        return None

    @property
    def voiceprint_config(self) -> dict[str, Any]:
        vp = self.raw.get("voiceprint")
        return dict(vp) if isinstance(vp, dict) else {}

    # ---- per-device routing (compatible with voice_devices.py) -------------

    def raw_device_settings(self, device_id: str) -> dict[str, Any]:
        wanted = _norm(device_id)
        if not wanted:
            return {}
        for key, value in (self.raw.get("voice_devices") or {}).items():
            if _norm(key) == wanted:
                return dict(value) if isinstance(value, dict) else {}
        return {}

    def wants_server_audio(self, device_id: str) -> bool:
        if self.output_mode != "native_xiaomi":
            return True
        if _norm(device_id) in self.server_audio_env:
            return True
        return self.raw_device_settings(device_id).get("output") == "server_audio"

    def device_profile(self, device_id: str) -> DeviceProfile:
        dev = self.raw_device_settings(device_id)
        server_audio = self.wants_server_audio(device_id)
        modules = self.tts_modules
        requested_tts = str(dev.get("tts") or "").strip()
        if requested_tts and requested_tts in modules:
            tts_name = requested_tts
        else:
            if requested_tts:
                log.warning("voice_devices: %s asks for unknown TTS %r; using default %s",
                            device_id, requested_tts, self.default_tts_name)
            tts_name = self.default_tts_name
        tts_cfg = dict(modules.get(tts_name) or BUILTIN_TTS_DEFAULTS["SherpaOnnxTTS"])
        room = str(dev.get("room") or "").strip()
        reply_style = str(dev.get("reply_style") or "").strip()
        interval = int(dev.get("send_interval_ms") or self.default_send_interval_ms)
        return DeviceProfile(
            device_id=device_id,
            server_audio=server_audio,
            tts_name=tts_name,
            tts_config=tts_cfg,
            room=room,
            reply_style=reply_style,
            send_interval_ms=max(10, interval),
        )

    def context_lines(self, profile: DeviceProfile) -> list[str]:
        lines: list[str] = []
        if profile.room:
            lines.append(
                f"- Device room: {profile.room}（此刻你正运行在{profile.room}的这台设备上，用户在{profile.room}对它说话；"
                f"问到你在哪、是哪台设备时以这里为准，即使人设里提到别的音箱；"
                f"没有说明房间的设备指令和问题，指的就是{profile.room}）"
            )
        if profile.reply_style:
            lines.append(f"- Reply style: {REPLY_STYLES.get(profile.reply_style, profile.reply_style)}")
        return lines
