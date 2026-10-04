"""Opus via PyAV: 16 kHz / 60 ms uplink frames, downlink decoded to 48 kHz."""

import av
import numpy as np

UPLINK_RATE = 16000
UPLINK_FRAME = 960  # 60 ms at 16 kHz, what the xiaozhi protocol expects
DOWNLINK_RATE = 48000  # Opus decodes to any rate, whatever the server encoded at


class OpusEncoder:
    def __init__(self):
        self._pending = np.zeros(0, dtype=np.int16)
        self._pts = 0
        self._ctx = self._new_context()

    @staticmethod
    def _new_context():
        ctx = av.CodecContext.create("libopus", "w")
        ctx.sample_rate = UPLINK_RATE
        ctx.layout = "mono"
        ctx.format = "s16"
        ctx.options = {"application": "voip", "frame_duration": "60"}
        return ctx

    def reset(self):
        """Start a new utterance (fresh encoder state, no leftover samples)."""
        self._pending = np.zeros(0, dtype=np.int16)
        self._pts = 0
        self._ctx = self._new_context()

    def encode(self, samples: np.ndarray) -> list[bytes]:
        """samples: float32 at 16 kHz; returns complete Opus packets."""
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        self._pending = np.concatenate([self._pending, pcm])
        packets = []
        while len(self._pending) >= UPLINK_FRAME:
            frame = av.AudioFrame.from_ndarray(self._pending[:UPLINK_FRAME].reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = UPLINK_RATE
            frame.pts = self._pts
            self._pts += UPLINK_FRAME
            self._pending = self._pending[UPLINK_FRAME:]
            packets.extend(bytes(p) for p in self._ctx.encode(frame))
        return packets


class OpusDecoder:
    def __init__(self):
        self._ctx = self._new_context()

    @staticmethod
    def _new_context():
        ctx = av.CodecContext.create("opus", "r")
        ctx.sample_rate = DOWNLINK_RATE
        ctx.layout = "mono"
        return ctx

    def reset(self):
        self._ctx = self._new_context()

    def decode(self, packet: bytes) -> np.ndarray:
        """Returns float32 mono at 48 kHz (may be empty)."""
        frames = self._ctx.decode(av.Packet(packet))
        if not frames:
            return np.zeros(0, dtype=np.float32)
        out = np.concatenate([f.to_ndarray().reshape(f.layout.nb_channels, -1)[0] for f in frames])
        return out.astype(np.float32)
