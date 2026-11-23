"""Terminal audio-health diagnostics sink.

Preserves the exact JSONL schema and field allowlist of
deploy/sherpa-tts/xiaozhi-server-overrides/audio_health.py so existing
deploy/audio-health tooling continues to work unchanged.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import threading
import time
from typing import Any

_SCALARS = {
    "schema", "ts_ms", "capture_id", "window_s", "sample_rate", "input_rate_hz",
    "input_age_ms", "max_input_gap_ms", "rms", "peak", "zero_ratio", "clip_ratio",
    "level_samples", "kws_max_ms", "kws_rtf", "kws_mode", "mode", "state", "connected",
    "audio_ok", "reconnects_total", "uplink_queue_events", "mic_rate_hz",
    "mic_callback_samples_total", "mic_processed_samples_total", "mic_overflows_total",
    "mic_dropped_samples_total", "mic_worker_errors_total", "mic_callback_age_ms",
    "mic_worker_alive", "mic_queue_chunks", "mic_queue_peak_chunks", "mic_max_queue_age_ms",
    "mic_max_callback_gap_ms", "log_errors_total", "log_dropped_total",
}
_COUNTER_KEYS = {
    "input_samples", "input_packets", "kws_samples", "skipped_samples",
    "kws_seconds", "wake_hits", "kws_errors", "metadata_missing_packets",
}


def sanitize(health: Any) -> dict[str, Any]:
    if not isinstance(health, dict):
        return {}
    result: dict[str, Any] = {
        key: value
        for key, value in health.items()
        if key in _SCALARS
        and isinstance(value, (str, int, float, bool, type(None)))
        and (not isinstance(value, str) or len(value) <= 128)
    }
    for key in ("window", "totals"):
        values = health.get(key)
        if isinstance(values, dict):
            result[key] = {
                k: v
                for k, v in list(values.items())[:40]
                if isinstance(k, str)
                and (k in _COUNTER_KEYS or k.startswith("mode_"))
                and len(k) <= 64
                and isinstance(v, (int, float))
            }
    return result


class AudioHealthSink:
    """Background rotating JSONL writer for terminal audio_health summaries."""

    def __init__(self, path: Path, max_bytes: int = 1048576, backups: int = 3):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
        self._started = False
        self._lock = threading.Lock()
        self.errors = 0
        self.dropped = 0

    def _ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
            threading.Thread(target=self._writer_loop, name="audio-health-writer", daemon=True).start()

    def _writer_loop(self) -> None:
        handler: RotatingFileHandler | None = None
        while True:
            record = self._queue.get()
            try:
                if handler is None:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    handler = RotatingFileHandler(
                        self.path, maxBytes=self.max_bytes, backupCount=self.backups, encoding="utf-8"
                    )
                line = json.dumps(record, ensure_ascii=False, allow_nan=False)
                rec = logging.LogRecord("audio-health", logging.INFO, "", 0, line, (), None)
                if handler.shouldRollover(rec):
                    handler.doRollover()
                handler.stream.write(line + "\n")
                handler.flush()
            except Exception:
                self.errors += 1
                if handler is not None:
                    try:
                        handler.close()
                    except Exception:
                        pass
                handler = None

    def record(
        self,
        device_id: str,
        session_id: str,
        health_payload: Any,
        opus_packets_total: int,
        opus_bytes_total: int,
    ) -> None:
        clean = sanitize(health_payload)
        self._ensure_started()
        entry = {
            "schema": 1,
            "role": "backend",
            "event": "terminal_summary",
            "ts_ms": time.time_ns() // 1_000_000,
            "node": str(device_id or ""),
            "capture_id": clean.get("capture_id"),
            "session_id": str(session_id or ""),
            "client": clean,
            "received_opus_packets_total": opus_packets_total,
            "received_opus_bytes_total": opus_bytes_total,
            "log_errors_total": self.errors,
            "log_dropped_total": self.dropped,
        }
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            self.dropped += 1
