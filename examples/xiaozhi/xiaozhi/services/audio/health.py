"""Bounded metadata-only audio diagnostics; no audio/transcripts in the log.

HealthLog is also shipped in the other standalone voice example. Keep its schema
and counters in sync; deploy/audio-health/test_health.py tests either copy.
"""
import json
import logging
import logging.handlers
import os
import queue
import threading
import time
import uuid
from pathlib import Path

import numpy as np


class HealthLog:
    def __init__(self, role, node, path, interval=10.0):
        self.role, self.node, self.path = role, node, Path(path)
        self.interval = interval
        self.capture_id = str(uuid.uuid4())
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=128)
        self._stop = threading.Event()
        self._threads = []
        self._totals, self._previous, self._details = {}, {}, {}
        self._last_pcm = None
        self._last_seq = None
        self._next_sample = None
        self._last_report = time.monotonic()
        self._levels_reset()
        self.log_dropped = 0
        self.log_errors = 0

    def _levels_reset(self):
        self._n = self._zeros = self._clipped = 0
        self._square = self._peak = self._gap = self._kws_max = 0.0

    def start(self, probe=lambda: {}, observer=lambda record: None):
        if self._threads:
            return
        self._last_report = time.monotonic()
        def writer():
            handler = None
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    record = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    if handler is None:
                        self.path.parent.mkdir(parents=True, exist_ok=True)
                        handler = logging.handlers.RotatingFileHandler(self.path, maxBytes=1048576, backupCount=3, encoding="utf-8")
                        handler.setFormatter(logging.Formatter("%(message)s"))
                    # Call emit directly: errors must be counted instead of silently handled by logging.
                    line = json.dumps(record, ensure_ascii=False, allow_nan=False)
                    rec = logging.LogRecord("audio-health", logging.INFO, "", 0, line, (), None)
                    if handler.shouldRollover(rec):
                        handler.doRollover()
                    handler.stream.write(line + "\n")
                    handler.flush()
                except Exception:
                    self.log_errors += 1
                    if self.log_errors == 1:
                        logging.getLogger(__name__).warning("audio-health log unavailable: %s", self.path)
                    if handler is not None:
                        handler.close()
                    handler = None
            if handler is not None:
                handler.close()
        def monitor():
            while not self._stop.wait(self.interval):
                try:
                    extra = probe()
                except Exception as exc:
                    extra = {"probe_error": type(exc).__name__}
                summary = {**self.snapshot(), **extra}
                self.emit("summary", **summary)
                try:
                    observer({"schema": 1, "role": self.role, "node": self.node,
                              "ts_ms": time.time_ns() // 1000000, "capture_id": self.capture_id,
                              "log_dropped_total": self.log_dropped, "log_errors_total": self.log_errors, **summary})
                except Exception:
                    self.count("observer_errors")
        self._threads = [threading.Thread(target=writer, name="health-writer", daemon=True),
                         threading.Thread(target=monitor, name="health-monitor", daemon=True)]
        for thread in self._threads:
            thread.start()
        self.emit("health_start", interval_s=self.interval)

    def close(self):
        self.emit("health_stop", **self.snapshot())
        self._stop.set()
        for thread in reversed(self._threads):
            thread.join(timeout=1)

    def emit(self, event, **fields):
        record = {"schema": 1, "role": self.role, "node": self.node, "event": event,
                  "ts_ms": time.time_ns() // 1000000, "capture_id": self.capture_id,
                  "log_dropped_total": self.log_dropped, "log_errors_total": self.log_errors, **fields}
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self.log_dropped += 1

    def count(self, key, amount=1):
        with self._lock:
            self._totals[key] = self._totals.get(key, 0) + amount

    def update(self, **fields):
        with self._lock:
            self._details.update(fields)

    def pcm(self, samples, metadata=None):
        samples = np.asarray(samples, dtype=np.float32)
        n = samples.size
        if not n:
            return
        now = time.monotonic()
        square = float(np.dot(samples, samples))
        peak = float(np.max(np.abs(samples)))
        zeros = int(np.count_nonzero(samples == 0))
        clipped = int(np.count_nonzero(np.abs(samples) >= 32767 / 32768))
        transition = None
        with self._lock:
            if self._last_pcm is not None:
                self._gap = max(self._gap, (now - self._last_pcm) * 1000)
            self._last_pcm = now
            self._totals["input_samples"] = self._totals.get("input_samples", 0) + n
            self._totals["input_packets"] = self._totals.get("input_packets", 0) + 1
            self._n += n; self._square += square; self._peak = max(self._peak, peak)
            self._zeros += zeros; self._clipped += clipped
            if metadata and metadata.get("capture_id"):
                capture = metadata["capture_id"]
                if capture != self.capture_id:
                    transition = {"previous_capture_id": self.capture_id}
                    self.capture_id = capture
                    self._last_seq = self._next_sample = None
                seq = metadata.get("seq")
                if isinstance(seq, int):
                    if self._last_seq is not None:
                        if seq > self._last_seq + 1:
                            self._totals["sequence_gaps"] = self._totals.get("sequence_gaps", 0) + seq-self._last_seq-1
                        elif seq <= self._last_seq:
                            self._totals["sequence_reorders"] = self._totals.get("sequence_reorders", 0) + 1
                    self._last_seq = max(seq, self._last_seq or seq)
                    self._details["seq"] = seq
                start = metadata.get("sample_start")
                if isinstance(start, int):
                    if self._next_sample is not None and start > self._next_sample:
                        self._totals["missing_samples"] = self._totals.get("missing_samples", 0) + start-self._next_sample
                    self._next_sample = max(start+n, self._next_sample or 0)
                self._details["sender_ts_ms"] = metadata.get("ts_ms")
            elif self.role == "bridge":
                self._totals["metadata_missing_packets"] = self._totals.get("metadata_missing_packets", 0)+1
        if transition:
            self.emit("capture_changed", **transition)

    def kws(self, samples, mode, duration=0.0, hit=False, error=False):
        with self._lock:
            key = "kws_samples" if mode == "active" else "skipped_samples"
            self._totals[key] = self._totals.get(key, 0) + samples
            self._totals[f"mode_{mode}_samples"] = self._totals.get(f"mode_{mode}_samples", 0)+samples
            self._totals["kws_seconds"] = self._totals.get("kws_seconds", 0.0)+duration
            self._kws_max = max(self._kws_max, duration*1000)
            self._totals["wake_hits"] = self._totals.get("wake_hits", 0)+int(hit)
            self._totals["kws_errors"] = self._totals.get("kws_errors", 0)+int(error)
            changed = self._details.get("kws_mode") != mode
            self._details["kws_mode"] = mode
        if changed:
            self.emit("kws_mode", mode=mode)
        if hit:
            self.emit("wake_hit")
        if error:
            self.emit("kws_error")

    def peek(self):
        with self._lock:
            return {"capture_id": self.capture_id, **self._details, "totals": dict(self._totals),
                    "input_age_ms": None if self._last_pcm is None else (time.monotonic()-self._last_pcm)*1000,
                    "log_dropped_total": self.log_dropped, "log_errors_total": self.log_errors}

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            seconds = max(now-self._last_report, 0.001)
            delta = {key: value-self._previous.get(key, 0) for key, value in self._totals.items()}
            n = max(self._n, 1)
            result = {**self._details, "window_s": round(seconds, 3),
                      "sample_rate": 16000, "input_rate_hz": delta.get("input_samples", 0)/seconds,
                      "input_age_ms": None if self._last_pcm is None else (now-self._last_pcm)*1000,
                      "max_input_gap_ms": self._gap, "rms": (self._square/n)**0.5,
                      "peak": self._peak, "zero_ratio": self._zeros/n, "clip_ratio": self._clipped/n,
                      "level_samples": self._n, "kws_max_ms": self._kws_max,
                      "kws_rtf": delta.get("kws_seconds", 0)*16000/max(delta.get("kws_samples", 0), 1),
                      "window": delta, "totals": dict(self._totals)}
            self._previous = dict(self._totals)
            self._last_report = now
            self._levels_reset()
            return result


HEALTH = HealthLog("bridge", "xiaoai", os.getenv("OPEN_XIAOAI_HEALTH_LOG", "/app/logs/audio-health.jsonl"))
