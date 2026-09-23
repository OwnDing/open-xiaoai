import asyncio
import json
import shlex
import unittest
from types import SimpleNamespace

from xiaozhi.services.native_tts import (
    NativeTTSSettings,
    NativeXiaomiTTS,
    resolve_tts_output_mode,
)


class FakeSpeaker:
    def __init__(self, block_playback=False):
        self.block_playback = block_playback
        self.play_started = asyncio.Event()
        self.release_playback = asyncio.Event()
        self.generated_texts = []
        self.played_paths = []
        self.deleted_paths = []
        self.commands = []
        self.counter = 0

    async def run_shell(self, script, timeout=10000):
        self.commands.append(script)
        if script.startswith("ubus call mibrain text_to_speech"):
            payload = json.loads(shlex.split(script)[-1])
            self.generated_texts.append(payload["text"])
            self.counter += 1
            info = json.dumps({"path": f"/tmp/fake-{self.counter}.mp3"})
            return SimpleNamespace(
                stdout=json.dumps({"info": info}), stderr="", exit_code=0
            )

        if script.startswith("busybox mv"):
            return SimpleNamespace(stdout="16000\n", stderr="", exit_code=0)

        if script.startswith("miplayer -f"):
            self.played_paths.append(shlex.split(script)[-1])
            self.play_started.set()
            if self.block_playback:
                await self.release_playback.wait()
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

        if script.startswith("busybox rm -f"):
            self.deleted_paths.append(script)

        return SimpleNamespace(stdout="0\n", stderr="", exit_code=0)


class NativeXiaomiTTSTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, **overrides):
        values = {
            "target_chars": 10,
            "max_chars": 20,
            "flush_delay_ms": 10,
            "prefetch_segments": 2,
            "generate_timeout_ms": 1000,
            "play_timeout_ms": 1000,
            "max_file_bytes": 1024 * 1024,
        }
        values.update(overrides)
        return NativeTTSSettings(**values)

    async def test_generates_ahead_and_plays_in_order(self):
        speaker = FakeSpeaker()
        pipeline = NativeXiaomiTTS(speaker, self.settings())

        await pipeline.start("session-1")
        await pipeline.add_text("第一段回答。")
        await pipeline.add_text("这是第二段回答。")
        completed = await asyncio.wait_for(pipeline.finish(), timeout=1)

        self.assertTrue(completed)
        self.assertEqual(
            speaker.generated_texts,
            ["第一段回答。", "这是第二段回答。"],
        )
        self.assertEqual(len(speaker.played_paths), 2)
        self.assertFalse(pipeline.active)

    async def test_long_text_is_split_at_maximum_length(self):
        speaker = FakeSpeaker()
        pipeline = NativeXiaomiTTS(speaker, self.settings(max_chars=12))
        text = "第一句话比较短。第二句话也不算很长。第三句话用于验证切分。"

        await pipeline.start("session-2")
        await pipeline.add_text(text)
        completed = await asyncio.wait_for(pipeline.finish(), timeout=1)

        self.assertTrue(completed)
        self.assertEqual("".join(speaker.generated_texts), text)
        self.assertTrue(all(len(item) <= 12 for item in speaker.generated_texts))

    async def test_abort_cancels_playback_and_cleans_files(self):
        speaker = FakeSpeaker(block_playback=True)
        pipeline = NativeXiaomiTTS(speaker, self.settings())

        await pipeline.start("session-3")
        await pipeline.add_text("正在播放的回答。")
        await asyncio.wait_for(speaker.play_started.wait(), timeout=1)
        await asyncio.wait_for(pipeline.abort(), timeout=1)

        self.assertFalse(pipeline.active)
        self.assertTrue(any("killall miplayer" in item for item in speaker.commands))
        self.assertTrue(any("open-xiaoai-native-tts" in item for item in speaker.deleted_paths))

    def test_output_mode_validation(self):
        self.assertEqual(
            resolve_tts_output_mode({"mode": "sherpa"}, "native_xiaomi"),
            "native_xiaomi",
        )
        self.assertEqual(resolve_tts_output_mode({"mode": "invalid"}), "sherpa")


if __name__ == "__main__":
    unittest.main()
