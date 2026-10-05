"""Per-device settings for open-xiaoai, read from `voice_devices` in data/.config.yaml.

    voice_devices:
      "02:76:74:00:00:01":        # Device-Id header, quoted (YAML reads 02:76:... as a number)
        output: server_audio      # server_audio: send TTS audio; native_xiaomi: text only (default)
        tts: EdgeTTS              # any module under TTS:, default selected_module.TTS
        room: 书房                # Home Assistant area the device is in
        reply_style: sentence     # sentence, or free text added to the context

Nothing here is specific to one home: devices without an entry keep the
backend's defaults. Installed as core/utils/voice_devices.py by the Dockerfile.
"""

import logging
import os

log = logging.getLogger(__name__)

REPLY_STYLES = {
    # A one-word answer ("二") is too short for the TTS voice to be understood.
    "sentence": "用完整的一句话回答，不要只说一个字或一个词。",
}


def _norm(device_id) -> str:
    return str(device_id or "").strip().lower()


def settings(config: dict, device_id) -> dict:
    wanted = _norm(device_id)
    if not wanted:
        return {}
    for key, value in (config.get("voice_devices") or {}).items():
        if _norm(key) == wanted:
            return value if isinstance(value, dict) else {}
    return {}


def wants_server_audio(config: dict, device_id) -> bool:
    """True if this device plays server TTS audio even in native_xiaomi mode."""
    listed = {_norm(d) for d in os.getenv("XIAOZHI_SERVER_AUDIO_DEVICES", "").split(",") if d.strip()}
    if _norm(device_id) in listed:
        return True
    return settings(config, device_id).get("output") == "server_audio"


def tts_config(config: dict, device_id) -> dict:
    """config with selected_module.TTS replaced by the device's TTS module, if it has one."""
    name = settings(config, device_id).get("tts")
    if not name:
        return config
    if name not in (config.get("TTS") or {}):
        log.warning("voice_devices: %s asks for unknown TTS %r; using the default", device_id, name)
        return config
    result = dict(config)
    result["selected_module"] = {**(config.get("selected_module") or {}), "TTS": name}
    return result


def context_lines(config: dict, device_id) -> list[str]:
    device = settings(config, device_id)
    lines = []
    room = str(device.get("room") or "").strip()
    if room:
        lines.append(
            f"- Device room: {room}（用户正在这个房间里对这台设备说话；"
            f"没有说明房间的设备指令和问题，指的就是{room}）"
        )
    style = str(device.get("reply_style") or "").strip()
    if style:
        lines.append(f"- Reply style: {REPLY_STYLES.get(style, style)}")
    return lines


def add_context(prompt, config: dict, device_id):
    """Insert this device's lines at the end of the prompt's <context> block."""
    lines = context_lines(config, device_id)
    if not prompt or not lines or "</context>" not in prompt:
        return prompt
    head, sep, tail = prompt.rpartition("</context>")
    return head.rstrip("\n") + "\n" + "\n".join(lines) + "\n" + sep + tail
