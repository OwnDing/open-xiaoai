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
        self.paused = False
        self.thread = threading.Thread(target=self._detection_loop, daemon=True)
        self.thread.start()

    def get_file_path(self, file_name: str):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(current_dir, "../../../models", file_name)

    def pause(self):
        self.paused = True
        HEALTH.emit("kws_pause")

    def resume(self):
        self.paused = False
        HEALTH.emit("kws_resume")

    def _detection_loop(self):
        try:
            SherpaOnnx.start()
            HEALTH.emit("kws_ready")
        except Exception as exc:
            HEALTH.emit("kws_init_error", error=type(exc).__name__)
            raise
        self.stream.start_stream()
        while True:
            # 读取缓冲区音频数据
            frames = self.stream.read(
                AudioConfig.FRAME_SIZE, exception_on_overflow=False
            )

            state = get_xiaozhi().device_state
            mode = "paused" if self.paused else (getattr(state, "name", str(state)).lower()
                if state in [DeviceState.LISTENING, DeviceState.SPEAKING] else "active")
            if not frames:
                HEALTH.update(kws_thread_tick_ms=time.time_ns() // 1000000)
                time.sleep(0.01)
                continue
            if mode != "active":
                HEALTH.kws(len(frames) // 2, mode)
                time.sleep(0.01)
                continue
            started = time.monotonic()
            try:
                result = SherpaOnnx.kws(frames)
            except Exception:
                HEALTH.kws(len(frames) // 2, mode, time.monotonic()-started, error=True)
                raise
            HEALTH.kws(len(frames) // 2, mode, time.monotonic()-started, hit=bool(result))
            if result:
                print(f"🔥 触发唤醒: {result}")
                self.on_message(result)

    def on_message(self, text: str):
        asyncio.run_coroutine_threadsafe(
            EventManager.wakeup(text, "kws"),
            get_xiaozhi().loop,
        )


KWS = _KWS()
