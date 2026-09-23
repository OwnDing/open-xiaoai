from pathlib import Path


TARGET = Path("/opt/xiaozhi-esp32-server/core/providers/tts/index_stream.py")


def replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match, found {count}: {old[:80]!r}")
    return source.replace(old, new, 1)


source = TARGET.read_text(encoding="utf-8")

source = replace_once(
    source,
    '''        self.audio_format = "pcm"
        self.before_stop_play_files = []
''',
    '''        self.audio_format = "pcm"
        self.before_stop_play_files = []
        self.output_mode = os.getenv("XIAOZHI_TTS_OUTPUT_MODE", "sherpa").strip().lower()
        self.native_xiaomi_text_only = self.output_mode == "native_xiaomi"
''',
)

source = replace_once(
    source,
    """                    self.before_stop_play_files.clear()
""",
    """                    self.before_stop_play_files.clear()
                    # Start a fresh continuous PCM/Opus stream for this answer.
                    self.pcm_buffer.clear()
                    self.opus_encoder.reset_state()
""",
)

source = replace_once(
    source,
    """            else:
                self._process_before_stop_play_files()
        else:
            self._process_before_stop_play_files()

    def to_tts_single_stream(self, text, is_last=False):
""",
    """            else:
                if is_last:
                    self._flush_pcm_buffer()
                self._process_before_stop_play_files()
        else:
            if is_last:
                self._flush_pcm_buffer()
            self._process_before_stop_play_files()

    def _flush_pcm_buffer(self):
        if not self.pcm_buffer:
            return
        self.opus_encoder.encode_pcm_to_opus_stream(
            bytes(self.pcm_buffer),
            end_of_stream=True,
            callback=self.handle_opus,
        )
        self.pcm_buffer.clear()

    def to_tts_single_stream(self, text, is_last=False):
""",
)

source = replace_once(
    source,
    '''    async def text_to_speak(self, text, is_last):
        """流式处理TTS音频，每句只推送一次音频列表"""
        payload = {"text": text, "character": self.voice}
''',
    '''    async def text_to_speak(self, text, is_last):
        """流式处理TTS音频，每句只推送一次音频列表"""
        if self.native_xiaomi_text_only:
            # The bridge will synthesize these text segments with Xiaomi's
            # native mibrain service. Do not create or pace redundant audio.
            self.tts_audio_queue.put((SentenceType.FIRST, [], text))
            if is_last:
                self._process_before_stop_play_files()
            return

        payload = {"text": text, "character": self.voice}
''',
)

source = replace_once(
    source,
    """                    self.pcm_buffer.clear()
                    self.tts_audio_queue.put((SentenceType.FIRST, [], text))
""",
    """                    self.tts_audio_queue.put((SentenceType.FIRST, [], text))
""",
)

source = replace_once(
    source,
    """                    # flush 剩余不足一帧的数据
                    if self.pcm_buffer:
                        self.opus_encoder.encode_pcm_to_opus_stream(
                            bytes(self.pcm_buffer),
                            end_of_stream=True,
                            callback=self.handle_opus
                        )
                        self.pcm_buffer.clear()

                    # 如果是最后一段，输出音频获取完毕
                    if is_last:
                        self._process_before_stop_play_files()
""",
    """                    # Keep partial PCM across sentence boundaries. Only the
                    # final sentence pads and flushes the Opus frame.
                    if is_last:
                        self._flush_pcm_buffer()
                        self._process_before_stop_play_files()
""",
)

TARGET.write_text(source, encoding="utf-8")
