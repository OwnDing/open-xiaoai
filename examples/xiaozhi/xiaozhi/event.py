import asyncio
import concurrent.futures
import shlex
import threading

from config import APP_CONFIG
from xiaozhi.ref import (
    get_audio_codec,
    get_kws,
    get_speaker,
    get_vad,
    get_xiaoai,
    get_xiaozhi,
    set_speech_frames,
)
from xiaozhi.services.protocols.typing import AbortReason, DeviceState, ListeningMode
from xiaozhi.services.audio.health import HEALTH
from xiaozhi.utils.base import get_env


def get_vad_setting(key, default):
    return APP_CONFIG.get("vad", {}).get(key, default)


def get_barge_in_setting(key, default):
    return APP_CONFIG.get("barge_in", {}).get(key, default)


class Step:
    idle = "idle"
    on_interrupt = "on_interrupt"
    on_wakeup = "on_wakeup"
    on_barge_in = "on_barge_in"
    on_tts_start = "on_tts_start"
    on_tts_end = "on_tts_end"
    on_speech = "on_speech"
    on_silence = "on_silence"
    on_stt = "on_stt"


class __EventManager:
    def __init__(self):
        self.session_id = 0
        self.current_step = Step.idle
        self.next_step_future = None
        self.next_step_loop = None
        self.session_future = None
        self.state_lock = threading.Lock()
        # Input sample to start listening from after a barge-in.
        self.listen_from = None
        self._background = set()

    @staticmethod
    def _resolve_future(future, result):
        if not future.done():
            future.set_result(result)

    def _set_step(
        self,
        step: Step,
        step_data=None,
        new_session=False,
        ignored_steps=(),
    ):
        with self.state_lock:
            if self.current_step in ignored_steps:
                return None
            if new_session:
                self.session_id += 1
            session_id = self.session_id
            self.current_step = step
            future = self.next_step_future
            future_loop = self.next_step_loop
            self.next_step_future = None
            self.next_step_loop = None

        if future and future_loop and not future_loop.is_closed():
            future_loop.call_soon_threadsafe(
                self._resolve_future,
                future,
                (step, step_data),
            )
        return session_id

    def update_step(self, step: Step, step_data=None):
        if not get_env("CLI"):
            return
        self._set_step(step, step_data)

    def _is_current_session(self, session_id):
        with self.state_lock:
            return session_id == self.session_id

    async def wait_next_step(self, session_id, timeout=None):
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        with self.state_lock:
            if session_id != self.session_id:
                future.cancel()
                return ("interrupted", None)
            previous_future = self.next_step_future
            previous_loop = self.next_step_loop
            self.next_step_future = future
            self.next_step_loop = loop

        if previous_future and previous_loop and not previous_loop.is_closed():
            previous_loop.call_soon_threadsafe(
                self._resolve_future,
                previous_future,
                ("interrupted", None),
            )

        try:
            if timeout is None:
                result = await future
            else:
                result = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            result = ("timeout", None)
        finally:
            with self.state_lock:
                if self.next_step_future is future:
                    self.next_step_future = None
                    self.next_step_loop = None
            if not future.done():
                future.cancel()

        if not self._is_current_session(session_id):
            # 当前 session 已经结束
            return ("interrupted", None)
        return result

    def _begin_session(self, step, ignored_steps=()):
        if not get_env("CLI"):
            return
        session_id = self._set_step(
            step,
            new_session=True,
            ignored_steps=ignored_steps,
        )
        if session_id is None:
            return
        self.start_session(session_id, step)

    def on_interrupt(self):
        """用户打断（小爱同学）"""
        self._begin_session(Step.on_interrupt)

    def on_wakeup(self):
        """用户唤醒（你好小智）"""
        self._begin_session(Step.on_wakeup)

    def barge_in(self, text, position=None):
        """小七说话时用户喊了唤醒词：马上停下，接着听

        position: 唤醒词大约在哪个输入采样点结束；之后已经说出的话会补给 VAD。
        """
        canceller = getattr(get_xiaoai(), "echo", None)
        ratio = canceller.near_end_ratio_db() if canceller else None
        min_db = get_barge_in_setting("near_end_min_db", None)
        rejected = min_db is not None and ratio is not None and ratio < min_db
        HEALTH.emit("barge_in", keyword=text, near_end_db=None if ratio is None else round(ratio, 1),
                    rejected=rejected)
        if rejected:
            print(f"🙉 忽略疑似小七自己的声音: {text} ({ratio:.1f} dB)")
            return
        tail = int(get_barge_in_setting("keyword_tail_ms", 200)) * 16
        self.listen_from = None if position is None else max(0, position - tail)
        print(f"✋ 打断小七: {text}")
        self._begin_session(Step.on_barge_in)

    def on_tts_end(self, session_id):
        """TTS结束"""
        self._begin_session(
            Step.on_tts_end,
            ignored_steps=(Step.idle, Step.on_interrupt, Step.on_tts_end, Step.on_barge_in),
        )

    def on_tts_start(self, session_id):
        """TTS结束"""
        self.update_step(Step.on_tts_start)

    def on_speech(self, speech_buffer: bytes):
        """检测到声音（开始说话"""
        self.update_step(Step.on_speech, speech_buffer)

    def on_silence(self):
        """检测到静音（说话结束）"""
        self.update_step(Step.on_silence)

    def on_stt(self):
        """服务端识别出了用户说的话"""
        self.update_step(Step.on_stt)

    def _on_session_done(self, future):
        with self.state_lock:
            if self.session_future is future:
                self.session_future = None
        try:
            future.result()
        except concurrent.futures.CancelledError:
            pass
        except Exception as error:
            print(f"❌ 对话状态机异常: {error}")

    def start_session(self, session_id, trigger_step):
        xiaozhi = get_xiaozhi()
        loop = getattr(xiaozhi, "loop", None)
        if not loop or loop.is_closed() or not loop.is_running():
            print("❌ 对话状态机异常: 主事件循环不可用")
            return

        future = asyncio.run_coroutine_threadsafe(
            self.__start_session(session_id, trigger_step), loop
        )
        with self.state_lock:
            previous_future = self.session_future
            self.session_future = future
        if previous_future and not previous_future.done():
            previous_future.cancel()
        future.add_done_callback(self._on_session_done)

    async def __start_session(self, session_id, trigger_step):
        if not get_env("CLI"):
            return

        if not self._is_current_session(session_id):
            return

        vad = get_vad()
        codec = get_audio_codec()
        speaker = get_speaker()
        xiaozhi = get_xiaozhi()

        # 先取消之前的 VAD 检测和音频输入输出流
        xiaozhi.set_device_state(DeviceState.IDLE)
        listen_from = None
        if trigger_step == Step.on_barge_in:
            listen_from, self.listen_from = self.listen_from, None
            # Whatever the server still sends for the interrupted reply is dropped.
            xiaozhi.ignore_tts_until_stt()
        # TTS 正常结束时不要反向取消刚完成的任务。所有状态切换均在
        # XiaoZhi.loop 上执行，避免跨事件循环等待 Task。
        if trigger_step != Step.on_tts_end:
            await xiaozhi.abort_tts_output()
        if not self._is_current_session(session_id):
            return
        await xiaozhi.protocol.send_abort_speaking(AbortReason.ABORT)

        # 小爱同学唤醒时，直接打断
        if trigger_step == Step.on_interrupt:
            return

        if trigger_step == Step.on_barge_in:
            # A short tone instead of the wake greeting; listen at once. The
            # tone's echo is cancelled like 小七's voice.
            self._play_tone(speaker, get_barge_in_setting("prompt_tone", ""))

        # 只留一小段时间避开音箱自己的余音，然后马上开始听。
        # 以前要先等到 0.5s 安静才开始听，用户一接话就会被丢掉。
        if trigger_step == Step.on_tts_end:
            await asyncio.sleep(get_vad_setting("tts_end_guard_ms", 300) / 1000)
            if not self._is_current_session(session_id):
                return

        # 检查是否有人说话
        print(f"🎙️ 等待用户说话: session={session_id} trigger={trigger_step}")
        if listen_from is None:
            vad.resume("speech")
        else:
            vad.resume("speech", since=listen_from)
        step, speech_buffer = await self.wait_next_step(
            session_id,
            timeout=APP_CONFIG["wakeup"]["timeout"],
        )
        if step == "timeout":
            await self._end_session(session_id, xiaozhi, speaker)
            return
        if step != Step.on_speech:
            return

        # 开始说话
        set_speech_frames(speech_buffer)
        codec.input_stream.start_stream()  # 开启录音
        await xiaozhi.protocol.send_start_listening(ListeningMode.MANUAL)
        xiaozhi.set_device_state(DeviceState.LISTENING)

        # 等待说话结束
        vad.resume("silence")
        step, _ = await self.wait_next_step(session_id)
        if step != Step.on_silence:
            return

        # 停止说话
        await xiaozhi.protocol.send_stop_listening()
        xiaozhi.set_device_state(DeviceState.IDLE)

        # 服务端没识别出内容时不会回复，也就不会再触发 TTS 结束。
        # 不要一直干等：提示用户重说，然后重新开始听。
        step, _ = await self.wait_next_step(
            session_id, timeout=get_vad_setting("no_reply_timeout", 5)
        )
        if step != "timeout":
            return
        print("🤷 没有识别到用户说的内容，提示重说")
        prompt = get_vad_setting("no_reply_prompt", "我没听清，再说一遍？")
        if prompt:
            await speaker.play(text=prompt)
        if self._is_current_session(session_id):
            self._begin_session(Step.on_tts_end)

    def _play_tone(self, speaker, path):
        if not path:
            return
        task = asyncio.ensure_future(
            speaker.run_shell(f"miplayer -f {shlex.quote(path)} >/dev/null 2>&1", timeout=3000)
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _end_session(self, session_id, xiaozhi, speaker):
        with self.state_lock:
            if session_id != self.session_id:
                return
            self.current_step = Step.idle
        kws = get_kws()
        kws.pause()
        HEALTH.emit("session_exit_start", session_id=session_id, reason="no_speech_timeout")
        try:
            # IDLE stops VAD and the conversation streams. KWS has its own
            # stream, so keep it paused through the goodbye and its echo.
            xiaozhi.set_device_state(DeviceState.IDLE)
            print("👋 已退出唤醒")
            after_wakeup = APP_CONFIG["wakeup"].get("after_wakeup")
            if callable(after_wakeup):
                HEALTH.emit("session_exit_prompt_start", session_id=session_id)
                try:
                    await after_wakeup(speaker)
                except Exception as error:
                    HEALTH.emit("session_exit_prompt_error", session_id=session_id, error=type(error).__name__)
                    print(f"❌ 退出提示播放失败: {error}")
                else:
                    HEALTH.emit("session_exit_prompt_end", session_id=session_id)
                guard_ms = max(0, APP_CONFIG["wakeup"].get("exit_guard_ms", 300))
                await asyncio.sleep(guard_ms / 1000)
                HEALTH.emit("session_exit_guard_end", session_id=session_id, guard_ms=guard_ms)
        except asyncio.CancelledError:
            HEALTH.emit("session_exit_cancelled", session_id=session_id)
            raise
        finally:
            # resume only requests a reset; the inference thread owns the model.
            # Nested pauses keep an interrupted exit from unpausing a new wake.
            kws.resume(reason="session_exit")
            HEALTH.emit("session_exit_end", session_id=session_id, kws_paused=kws.paused)

    async def wakeup(self, text, source):
        before_wakeup = APP_CONFIG["wakeup"]["before_wakeup"]
        get_kws().pause()  # 暂停 KWS 检测
        try:
            wakeup = await before_wakeup(get_speaker(), text, source)
        except Exception as error:
            wakeup = False
            print(f"❌ 唤醒处理失败: {error}")
        finally:
            get_kws().resume()  # 恢复 KWS 检测
        if wakeup:
            self.on_wakeup()


EventManager = __EventManager()
