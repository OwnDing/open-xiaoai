"""Receive terminal diagnostics without entering listen, ASR, LLM or idle timers."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import threading
import time

_QUEUE = queue.Queue(maxsize=128)
_STARTED = False
_START_LOCK = threading.Lock()
_ERRORS = 0
_DROPPED = 0
# Explicit allowlist: a client cannot make the server persist audio, transcripts or tokens.
_SCALARS = {"schema", "ts_ms", "capture_id", "window_s", "sample_rate", "input_rate_hz",
            "input_age_ms", "max_input_gap_ms", "rms", "peak", "zero_ratio", "clip_ratio",
            "level_samples", "kws_max_ms", "kws_rtf", "kws_mode", "mode", "state", "connected",
            "audio_ok", "reconnects_total", "uplink_queue_events", "mic_rate_hz",
            "mic_callback_samples_total", "mic_processed_samples_total", "mic_overflows_total",
            "mic_dropped_samples_total", "mic_worker_errors_total", "mic_callback_age_ms",
            "mic_worker_alive", "mic_queue_chunks", "mic_queue_peak_chunks", "mic_max_queue_age_ms",
            "mic_max_callback_gap_ms", "log_errors_total", "log_dropped_total"}


def sanitize(health):
    if not isinstance(health, dict):
        return {}
    result = {key: value for key, value in health.items() if key in _SCALARS
              and isinstance(value, (str, int, float, bool, type(None)))
              and (not isinstance(value, str) or len(value) <= 128)}
    for key in ("window", "totals"):
        values = health.get(key)
        if isinstance(values, dict):
            result[key] = {k: v for k, v in list(values.items())[:40]
                           if isinstance(k, str) and (k in {"input_samples", "input_packets", "kws_samples",
                               "skipped_samples", "kws_seconds", "wake_hits", "kws_errors", "metadata_missing_packets"}
                               or k.startswith("mode_")) and len(k) <= 64 and isinstance(v, (int, float))}
    return result


def _start_writer():
    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        threading.Thread(target=_write, name="audio-health-writer", daemon=True).start()


def _write():
    global _ERRORS
    handler = None
    while True:
        record = _QUEUE.get()
        try:
            if handler is None:
                path = Path("data/audio-health.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(path, maxBytes=1048576, backupCount=3, encoding="utf-8")
            line = json.dumps(record, ensure_ascii=False, allow_nan=False)
            rec = logging.LogRecord("audio-health", logging.INFO, "", 0, line, (), None)
            if handler.shouldRollover(rec):
                handler.doRollover()
            handler.stream.write(line + "\n")
            handler.flush()
        except Exception:
            _ERRORS += 1
            if handler:
                handler.close()
            handler = None


def handle_health(conn, message):
    """True only for diagnostic packets; unknown packets keep their original route."""
    global _DROPPED
    if len(message) > 16384:
        return False
    # Cheap prefix check avoids parsing every normal application message twice.
    if '"audio_health"' not in message:
        return False
    try:
        packet = json.loads(message)
    except (ValueError, TypeError):
        return False
    if not isinstance(packet, dict) or packet.get("type") != "audio_health":
        return False
    health = sanitize(packet.get("health"))
    _start_writer()
    record = {"schema": 1, "role": "backend", "event": "terminal_summary",
              "ts_ms": time.time_ns() // 1000000,
              "node": str(getattr(conn, "device_id", "")), "capture_id": health.get("capture_id"),
              "session_id": str(getattr(conn, "session_id", "")), "client": health,
              "received_opus_packets_total": getattr(conn, "_health_opus_packets", 0),
              "received_opus_bytes_total": getattr(conn, "_health_opus_bytes", 0),
              "log_errors_total": _ERRORS, "log_dropped_total": _DROPPED}
    try:
        _QUEUE.put_nowait(record)
    except queue.Full:
        _DROPPED += 1
    return True


def count_audio(conn, message):
    conn._health_opus_packets = getattr(conn, "_health_opus_packets", 0) + 1
    conn._health_opus_bytes = getattr(conn, "_health_opus_bytes", 0) + len(message)
