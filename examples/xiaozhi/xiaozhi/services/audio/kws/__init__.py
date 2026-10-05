import asyncio
import os
import threading
import time

from config import APP_CONFIG
from xiaozhi.event import EventManager
from xiaozhi.services.audio.health import HEALTH
from xiaozhi.ref import get_xiaozhi, set_kws
from xiaozhi.services.audio.kws.sherpa import SherpaOnnx
from xiaozhi.services.audio.stream import MyAudio
from xiaozhi.services.protocols.typing import AudioConfig, DeviceState
from xiaozhi.utils.base import get_env


class _KWS:
    def __init__(self):
        set_kws(self)
        self._control_lock = threading.Lock()
        self._pause_depth = 0
        self.paused = False
        self._revision = 0
        self._reset_reason = None
        self._last_mode = "active"

    def start(self):
        if not get_env("CLI"):
            return

        self.audio = MyAudio.create()
        self.stream = self.audio.open(
            format=AudioConfig.FORMAT,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=AudioConfig.FRAME_SIZE,
            start=True,
        )

        # 启动 KWS 服务
        self.thread = threading.Thread(target=self._detection_loop, daemon=True)
        self.thread.start()

    def get_file_path(self, file_name: str):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(current_dir, "../../../models", file_name)

    def pause(self):
        with self._control_lock:
            self._pause_depth += 1
            self.paused = True
            self._revision += 1
            depth = self._pause_depth
        HEALTH.emit("kws_pause", pause_depth=depth)

    def resume(self, reason="resume"):
        with self._control_lock:
            self._pause_depth = max(0, self._pause_depth - 1)
            self.paused = self._pause_depth > 0
            if not self.paused:
                self._reset_reason = reason
                self._revision += 1
            paused = self.paused
        HEALTH.emit("kws_resume", paused=paused, reset_pending=not paused, reason=reason)

    def _mode(self):
        state = get_xiaozhi().device_state
        if self.paused:
            return "paused"
        return state if state in [DeviceState.LISTENING, DeviceState.SPEAKING] else "active"

    def _discard_buffer(self):
        if hasattr(self.stream, "input_bytes"):
            return len(self.stream.read()) // 2
        available = self.stream.get_read_available()
        if available:
            return len(self.stream.read(available, exception_on_overflow=False)) // 2
        return 0

    def _process_frames(self, frames):
        # Controls never touch the ONNX stream. Only this detection thread may
        # decode/reset it, even if a pause arrives during an in-flight decode.
        with self._control_lock:
            mode = self._mode()
            if mode != self._last_mode:
                self._revision += 1
            revision = self._revision
            reason = self._reset_reason
            if mode == "active" and self._last_mode != "active" and reason is None:
                reason = "mode_active"
            if mode == "active":
                self._reset_reason = None
            self._last_mode = mode
        if mode != "active":
            if frames:
                HEALTH.kws(len(frames) // 2, mode)
            return
        if reason is not None:
            discarded = len(frames) // 2
            try:
                discarded += self._discard_buffer()
                SherpaOnnx.reset()
            except Exception as error:
                HEALTH.kws(discarded, "reset", error=True)
                HEALTH.emit("kws_reset_error", reason=reason, error=type(error).__name__)
                raise
            if discarded:
                HEALTH.kws(discarded, "reset")
            HEALTH.emit("kws_reset", reason=reason, discarded_samples=discarded, revision=revision)
            return
        if not frames:
            return
        started = time.monotonic()
        try:
            result = SherpaOnnx.kws(frames)
        except Exception:
            HEALTH.kws(len(frames) // 2, mode, time.monotonic()-started, error=True)
            raise
        with self._control_lock:
            current = revision == self._revision and self._mode() == "active"
        if result and not current:
            HEALTH.emit("kws_stale_hit", revision=revision)
        HEALTH.kws(len(frames) // 2, mode, time.monotonic()-started, hit=bool(result) and current)
        if result and current:
            print(f"🔥 触发唤醒: {result}")
            self.on_message(result, revision)

    def _detection_loop(self):
        try:
            SherpaOnnx.start()
            HEALTH.emit("kws_ready")
        except Exception as exc:
            HEALTH.emit("kws_init_error", error=type(exc).__name__)
            raise
        self.stream.start_stream()
        while True:
            # Rearm before reading the next frame, so fresh speech arriving
            # after the boundary does not become the frame discarded by reset.
            self._process_frames(b"")
            # 读取缓冲区音频数据
            frames = self.stream.read(
                AudioConfig.FRAME_SIZE, exception_on_overflow=False
            )

            self._process_frames(frames)
            HEALTH.update(kws_thread_tick_ms=time.time_ns() // 1000000)
            if not frames or self.paused:
                time.sleep(0.01)

    async def _dispatch_wakeup(self, text, revision):
        with self._control_lock:
            current = revision == self._revision and self._mode() == "active"
        if current:
            await EventManager.wakeup(text, "kws")
        else:
            HEALTH.emit("kws_stale_hit", revision=revision)

    def on_message(self, text: str, revision: int):
        asyncio.run_coroutine_threadsafe(
            self._dispatch_wakeup(text, revision),
            get_xiaozhi().loop,
        )


KWS = _KWS()
