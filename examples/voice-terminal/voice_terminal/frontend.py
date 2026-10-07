"""Mic front end: WebRTC APM (high-pass, noise suppression, gain) on 10 ms frames."""

import numpy as np

RATE = 16000
FRAME = RATE // 100  # APM works on exactly 10 ms


class Frontend:
    def __init__(self, stages):
        self.stages = list(stages)
        self._module = None
        if self.stages:
            from livekit import rtc

            self._rtc = rtc
            self._module = rtc.AudioProcessingModule(
                echo_cancellation=False,
                noise_suppression="ns" in self.stages,
                high_pass_filter="hpf" in self.stages,
                auto_gain_control="agc" in self.stages,
            )

    def close(self):
        # Release the native APM while livekit's FFI is still loaded; freeing it
        # during interpreter shutdown trips an assertion in livekit.
        self._module = None

    def process(self, frame: np.ndarray) -> np.ndarray:
        """frame: float32, FRAME samples at 16 kHz; returns the processed frame."""
        if self._module is None:
            return frame
        pcm = (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16)
        audio = self._rtc.AudioFrame(pcm.tobytes(), RATE, 1, FRAME)
        self._module.process_stream(audio)
        return np.frombuffer(audio.data, dtype=np.int16).astype(np.float32) / 32768.0
