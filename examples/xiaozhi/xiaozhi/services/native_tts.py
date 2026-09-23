import asyncio
import json
import shlex
import uuid
from dataclasses import dataclass


VALID_OUTPUT_MODES = {"sherpa", "native_xiaomi"}


def resolve_tts_output_mode(config, env_value=None):
    configured = env_value or config.get("mode", "sherpa")
    mode = str(configured).strip().lower()
    if mode not in VALID_OUTPUT_MODES:
        print(f"⚠️ 未知 TTS 输出模式 {mode!r}，回退到 sherpa")
        return "sherpa"
    return mode


@dataclass
class NativeTTSSettings:
    target_chars: int = 80
    max_chars: int = 120
    flush_delay_ms: int = 250
    prefetch_segments: int = 2
    generate_timeout_ms: int = 5000
    play_timeout_ms: int = 10 * 60 * 1000
    max_file_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 8 * 1024 * 1024

    @classmethod
    def from_config(cls, config):
        values = {}
        for field_name in cls.__dataclass_fields__:
            if field_name in config:
                values[field_name] = int(config[field_name])
        settings = cls(**values)
        settings.target_chars = max(1, settings.target_chars)
        settings.max_chars = max(settings.target_chars, settings.max_chars)
        settings.flush_delay_ms = max(0, settings.flush_delay_ms)
        settings.prefetch_segments = max(1, settings.prefetch_segments)
        settings.generate_timeout_ms = max(1000, settings.generate_timeout_ms)
        settings.play_timeout_ms = max(1000, settings.play_timeout_ms)
        settings.max_file_bytes = max(1024, settings.max_file_bytes)
        settings.max_total_bytes = max(
            settings.max_file_bytes, settings.max_total_bytes
        )
        return settings


class NativeXiaomiTTS:
    """Pipeline Xiaomi's native TTS generation and miplayer playback."""

    _BOUNDARIES = "。！？!?；;，,\n"
    _FILE_PREFIX = "/tmp/open-xiaoai-native-tts-"

    def __init__(self, speaker, settings=None):
        self.speaker = speaker
        self.settings = settings or NativeTTSSettings()
        self._token = 0
        self._active = False
        self._aborted = False
        self._finish_requested = False
        self._pending_text = ""
        self._is_first_segment = True
        self._segment_index = 0
        self._segment_queue = None
        self._audio_queue = None
        self._generation_task = None
        self._playback_task = None
        self._delayed_flush_task = None
        self._done_event = None
        self._generated_files = set()
        self._generated_sizes = {}
        self._resume_music = False
        self._music_state_checked = False
        self._error = None
        self._session_key = ""

    @property
    def active(self):
        return self._active

    @property
    def error(self):
        return self._error

    async def start(self, session_id=None):
        if self._active:
            await self.abort()
        else:
            await self._cleanup_stale_files()

        self._token += 1
        token = self._token
        self._active = True
        self._aborted = False
        self._finish_requested = False
        self._pending_text = ""
        self._is_first_segment = True
        self._segment_index = 0
        self._segment_queue = asyncio.Queue()
        self._audio_queue = asyncio.Queue(maxsize=self.settings.prefetch_segments)
        self._done_event = asyncio.Event()
        self._generated_files = set()
        self._generated_sizes = {}
        self._resume_music = False
        self._music_state_checked = False
        self._error = None
        self._session_key = self._safe_session_key(session_id)
        self._generation_task = asyncio.create_task(self._generation_worker(token))
        self._playback_task = asyncio.create_task(self._playback_worker(token))
        print(f"🔊 原生小爱 TTS 会话已开始: {self._session_key}")
        return token

    async def add_text(self, text):
        if not self._active or self._finish_requested:
            return

        text = str(text or "").strip()
        if not text:
            return

        self._pending_text += text
        if self._is_first_segment:
            self._is_first_segment = False
            await self._flush_pending(force=True)
            return

        if len(self._pending_text) >= self.settings.target_chars:
            await self._cancel_delayed_flush()
            await self._flush_pending(force=False)
        else:
            self._schedule_delayed_flush()

    async def finish(self):
        if not self._active:
            return False

        token = self._token
        if not self._finish_requested:
            self._finish_requested = True
            await self._cancel_delayed_flush()
            await self._flush_pending(force=True)
            await self._segment_queue.put(None)

        await self._done_event.wait()
        return token == self._token and not self._aborted

    async def abort(self):
        if not self._active and not self._tasks_running():
            return

        self._aborted = True
        self._active = False
        self._token += 1
        await self._cancel_delayed_flush()

        try:
            await self.speaker.run_shell(
                "busybox killall miplayer 2>/dev/null || true", timeout=2000
            )
        except Exception:
            pass

        tasks = [self._generation_task, self._playback_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in tasks if task), return_exceptions=True
        )

        await self._cleanup_generated_files()
        await self._restore_music_if_needed()
        if self._done_event:
            self._done_event.set()
        print("⏹️ 原生小爱 TTS 已中断")

    async def _generation_worker(self, token):
        try:
            while token == self._token:
                text = await self._segment_queue.get()
                if text is None:
                    await self._audio_queue.put(None)
                    return

                try:
                    audio_path = await self._generate_audio(text, token)
                    await self._audio_queue.put((audio_path, text))
                except Exception as error:
                    self._error = str(error)
                    print(f"❌ 原生小爱 TTS 合成失败: {error}")
                    await self._audio_queue.put(None)
                    return
        except asyncio.CancelledError:
            raise

    async def _playback_worker(self, token):
        try:
            while token == self._token:
                item = await self._audio_queue.get()
                if item is None:
                    break

                audio_path, text = item
                if not self._music_state_checked:
                    await self._pause_music_if_needed()

                started = asyncio.get_running_loop().time()
                try:
                    result = await self.speaker.run_shell(
                        f"miplayer -f {shlex.quote(audio_path)}",
                        timeout=self.settings.play_timeout_ms,
                    )
                    if result.exit_code != 0:
                        raise RuntimeError(
                            result.stderr.strip()
                            or f"miplayer exit code {result.exit_code}"
                        )
                    elapsed = asyncio.get_running_loop().time() - started
                    print(
                        f"✅ 原生小爱 TTS 播放完成: chars={len(text)} "
                        f"elapsed={elapsed:.3f}s"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self._error = str(error)
                    print(f"❌ 原生小爱 TTS 播放失败: {error}")
                finally:
                    await self._delete_audio_file(audio_path)
        except asyncio.CancelledError:
            raise
        finally:
            if token == self._token:
                await self._restore_music_if_needed()
                self._active = False
                self._done_event.set()

    async def _generate_audio(self, text, token):
        if token != self._token:
            raise asyncio.CancelledError

        payload = json.dumps(
            {"text": text, "save": 1}, ensure_ascii=False, separators=(",", ":")
        )
        started = asyncio.get_running_loop().time()
        result = await self.speaker.run_shell(
            f"ubus call mibrain text_to_speech {shlex.quote(payload)}",
            timeout=self.settings.generate_timeout_ms,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                result.stderr.strip() or f"mibrain exit code {result.exit_code}"
            )

        try:
            response = json.loads(result.stdout)
            info = response.get("info")
            if isinstance(info, str):
                info = json.loads(info)
            generated_path = info.get("path") if isinstance(info, dict) else None
        except Exception as error:
            raise RuntimeError(f"无法解析 mibrain 响应: {result.stdout!r}") from error

        if not generated_path or not str(generated_path).startswith("/"):
            raise RuntimeError("mibrain 未返回有效音频路径")

        self._segment_index += 1
        audio_path = (
            f"{self._FILE_PREFIX}{self._session_key}-{self._segment_index}.mp3"
        )
        move_result = await self.speaker.run_shell(
            f"busybox mv {shlex.quote(generated_path)} {shlex.quote(audio_path)} "
            f"&& wc -c < {shlex.quote(audio_path)}",
            timeout=2000,
        )
        if move_result.exit_code != 0:
            raise RuntimeError(
                move_result.stderr.strip() or "无法保存原生 TTS 临时音频"
            )

        try:
            size_bytes = int(move_result.stdout.strip())
        except ValueError as error:
            raise RuntimeError("无法读取原生 TTS 音频大小") from error

        self._generated_files.add(audio_path)
        if size_bytes > self.settings.max_file_bytes:
            await self._delete_audio_file(audio_path)
            raise RuntimeError(
                f"原生 TTS 音频超过限制: {size_bytes} bytes"
            )
        if sum(self._generated_sizes.values()) + size_bytes > self.settings.max_total_bytes:
            await self._delete_audio_file(audio_path)
            raise RuntimeError("原生 TTS 临时音频总量超过限制")
        self._generated_sizes[audio_path] = size_bytes

        elapsed = asyncio.get_running_loop().time() - started
        estimated_audio_seconds = size_bytes * 8 / 32000
        rtf = elapsed / estimated_audio_seconds if estimated_audio_seconds else 0
        print(
            f"🎵 原生小爱 TTS 已生成: chars={len(text)} bytes={size_bytes} "
            f"elapsed={elapsed:.3f}s estimated_rtf={rtf:.3f}"
        )
        return audio_path

    async def _flush_pending(self, force):
        while self._pending_text:
            if not force and len(self._pending_text) < self.settings.target_chars:
                return

            if len(self._pending_text) <= self.settings.max_chars:
                segment = self._pending_text
                self._pending_text = ""
            else:
                cut = self._find_split_position(self._pending_text)
                segment = self._pending_text[:cut]
                self._pending_text = self._pending_text[cut:]

            segment = segment.strip()
            if segment:
                await self._segment_queue.put(segment)

    def _find_split_position(self, text):
        limit = self.settings.max_chars
        minimum = max(1, self.settings.target_chars // 2)
        candidate = text[:limit]
        positions = [candidate.rfind(mark) for mark in self._BOUNDARIES]
        split_at = max(positions) + 1
        return split_at if split_at >= minimum else limit

    def _schedule_delayed_flush(self):
        if self._delayed_flush_task and not self._delayed_flush_task.done():
            self._delayed_flush_task.cancel()
        token = self._token
        self._delayed_flush_task = asyncio.create_task(
            self._delayed_flush(token)
        )

    async def _delayed_flush(self, token):
        try:
            await asyncio.sleep(self.settings.flush_delay_ms / 1000)
            if token == self._token and self._active:
                await self._flush_pending(force=True)
        except asyncio.CancelledError:
            pass

    async def _cancel_delayed_flush(self):
        task = self._delayed_flush_task
        self._delayed_flush_task = None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _pause_music_if_needed(self):
        self._music_state_checked = True
        try:
            result = await self.speaker.run_shell(
                "/usr/bin/mphelper mute_stat", timeout=2000
            )
            self._resume_music = result.stdout.strip() == "1"
            if self._resume_music:
                await self.speaker.run_shell("/usr/bin/mphelper pause", timeout=2000)
        except Exception:
            self._resume_music = False

    async def _restore_music_if_needed(self):
        if not self._resume_music:
            return
        self._resume_music = False
        try:
            await self.speaker.run_shell("/usr/bin/mphelper play", timeout=2000)
        except Exception:
            pass

    async def _delete_audio_file(self, audio_path):
        self._generated_files.discard(audio_path)
        self._generated_sizes.pop(audio_path, None)
        try:
            await self.speaker.run_shell(
                f"busybox rm -f {shlex.quote(audio_path)}", timeout=2000
            )
        except Exception:
            pass

    async def _cleanup_generated_files(self):
        paths = list(self._generated_files)
        self._generated_files.clear()
        self._generated_sizes.clear()
        for audio_path in paths:
            await self._delete_audio_file(audio_path)
        await self._cleanup_stale_files()

    async def _cleanup_stale_files(self):
        try:
            await self.speaker.run_shell(
                f"busybox rm -f {self._FILE_PREFIX}*.mp3", timeout=2000
            )
        except Exception:
            pass

    def _tasks_running(self):
        return any(
            task and not task.done()
            for task in (self._generation_task, self._playback_task)
        )

    @staticmethod
    def _safe_session_key(session_id):
        if session_id:
            safe = "".join(ch for ch in str(session_id) if ch.isalnum())
            if safe:
                return safe[:16]
        return uuid.uuid4().hex[:12]
