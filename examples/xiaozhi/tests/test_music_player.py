import asyncio
import json
import os
import re
import tempfile
import unittest
import urllib.request
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import xiaozhi.event as event_module
from xiaozhi.event import Step
from xiaozhi.services.audio.kws import _KWS
from xiaozhi.services.music import MusicService
from xiaozhi.services.music.player import MusicPlayer, MusicSettings, softvol
from xiaozhi.services.music.server import byte_range, track_span
from xiaozhi.services.protocols.typing import DeviceState

try:
    from tests.test_music_library import library
except ImportError:  # run from inside tests/
    from test_music_library import library


class FakeSpeaker:
    """run_shell on the speaker: music processes that end when told to."""

    def __init__(self):
        self.scripts = []
        self.pid = 100
        self.ended = {}
        self.left = ""  # a song still playing from before a restart

    def end(self, pid):
        self.ended.setdefault(pid, asyncio.Event()).set()

    async def __call__(self, script, timeout=10000):
        self.scripts.append(script)
        if "netstat" in script:
            return SimpleNamespace(stdout="192.168.5.10:4399\n", stderr="", exit_code=0)
        if "echo $! > pid" in script:
            self.pid += 1
            return SimpleNamespace(stdout=f"pid={self.pid}\n", stderr="", exit_code=0)
        if script.startswith("pidof"):
            return SimpleNamespace(stdout=self.left, stderr="", exit_code=0 if self.left else 1)
        if "kill -0" in script:
            pid = int(re.search(r"kill -0 (\d+)", script).group(1))
            await self.ended.setdefault(pid, asyncio.Event()).wait()
            return SimpleNamespace(stdout="ended\n", stderr="", exit_code=0)
        return SimpleNamespace(stdout="", stderr="", exit_code=0)

    def started(self):
        return [s for s in self.scripts if "echo $! > pid" in s]

    def volumes(self):
        return [int(v) for s in self.scripts for v in re.findall(r"cset name=xqmusicvol (\d+)", s)]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PlayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.speaker = FakeSpeaker()
        self.clock = Clock()
        self.active = False
        self.player = MusicPlayer(library(), self.speaker, MusicSettings(enabled=True),
                                  session_active=lambda: self.active, clock=self.clock)
        patcher = patch("xiaozhi.services.music.player.HEALTH")
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        for task in list(self.player._tasks):
            task.cancel()
        await asyncio.gather(*self.player._tasks, return_exceptions=True)

    async def settle(self):
        for _ in range(20):
            await asyncio.sleep(0)

    async def test_play_a_song_from_the_bridge_at_full_music_volume(self):
        result = await self.player.command("播放梁静茹的勇气")
        self.assertEqual(result, {"handled": True, "say": "好的，梁静茹的勇气。", "end": True})
        script = self.speaker.started()[-1]
        track = self.player.current
        self.assertIn(f"http://192.168.5.10:4400/music/track/{track.id}.mp3", script)
        self.assertIn("cset name=xqmusicvol 255", script)
        self.assertIn("ALSA_CONFIG_PATH=/tmp/xq-music/alsa.conf ./xqmusic -f", script)
        self.assertIn("cp /usr/bin/miplayer xqmusic", script)  # a copy: killall miplayer spares it
        self.assertTrue(self.player.playing)

    async def test_requests_that_are_not_music_pass(self):
        for text in ["今天天气怎么样", "放假了吗", "暂停", "下一首", "这是什么歌", "继续"]:
            self.assertFalse((await self.player.command(text))["handled"], text)
        self.assertEqual(self.speaker.started(), [])

    async def test_random_play_says_what_it_picked(self):
        for _ in range(10):  # the pick is random; songs with and without a singer
            result = await self.player.command("随便放一首歌")
            track = self.player.current
            expected = f"好的，先放{track.artist}的{track.title}。" if track.artist else f"好的，先放{track.title}。"
            self.assertEqual(result["say"], expected)

    async def test_questions_about_the_library(self):
        lib = self.player.library
        singers = {t.artist for t in lib.tracks if t.artist}
        result = await self.player.command("曲库里一共有多少首歌")
        self.assertEqual(result, {"handled": True, "end": False,
                                  "say": f"曲库里一共有{len(lib.tracks)}首歌，{len(singers)}位歌手。"})
        self.assertTrue((await self.player.command("有哪些歌手"))["say"].startswith(f"曲库里有{len(singers)}位歌手，歌比较多的有梁静茹"))
        self.assertEqual((await self.player.command("有没有梁静茹的歌"))["say"], "有，梁静茹的歌有3首。")
        self.assertEqual((await self.player.command("有没有偶阵雨这首歌"))["say"], "有，梁静茹的偶阵雨。")
        self.assertEqual((await self.player.command("有没有梁静茹的情歌"))["say"], "有梁静茹的歌，但没有情歌。")
        self.assertEqual((await self.player.command("有没有梁静茹的勇敢"))["say"], "有梁静茹的歌，但没有勇敢。")
        self.assertEqual((await self.player.command("有没有王菲的歌"))["say"], "曲库里没有王菲。")
        self.assertEqual((await self.player.command("刘德华有几首歌"))["say"], "有，刘德华的歌有2首。")
        self.assertFalse((await self.player.command("有没有下雨"))["handled"])
        self.assertEqual(self.speaker.started(), [])  # questions never start music

    async def test_album_of_the_song_playing(self):
        await self.player.command("播放梁静茹的偶阵雨")
        self.player.current.album = "爱久见人心"
        self.assertEqual((await self.player.command("这首歌是哪张专辑的"))["say"],
                         "这首是梁静茹的偶阵雨，出自爱久见人心。")

    async def test_strict_names_must_be_known(self):
        self.assertFalse((await self.player.command("放勇敢"))["handled"])
        self.assertTrue((await self.player.command("放周杰伦"))["handled"])

    async def test_not_found_keeps_listening(self):
        result = await self.player.command("我想听不存在的东西")
        self.assertEqual(result, {"handled": True, "say": "曲库里没找到不存在的东西。", "end": False})
        # "播放狂飙" without a song or singer may be a TV show: the model decides.
        self.assertFalse((await self.player.command("播放狂飙"))["handled"])
        result = await self.player.command("播放梁静茹的情歌")
        self.assertEqual(result["say"], "没找到情歌，先放梁静茹的歌。")

    async def test_stop_and_resume_an_mp3_where_it_was(self):
        await self.player.command("播放梁静茹的勇气")
        self.clock.now += 95
        result = await self.player.command("暂停")
        self.assertEqual(result, {"handled": True, "say": "", "end": True})
        self.assertFalse(self.player.playing)
        self.assertIn("killall xqmusic", self.speaker.scripts[-1])
        self.assertEqual(round(self.player.position), 95)
        await self.player.command("继续播放")
        self.assertIn("?start=95", self.speaker.started()[-1])
        self.assertTrue(self.player.playing)

    async def test_a_bare_stop_stops_music_left_over_from_a_restart(self):
        self.speaker.left = "2752\n"
        self.assertTrue((await self.player.command("暂停"))["handled"])
        self.assertIn("killall xqmusic", self.speaker.scripts[-1])

    async def test_a_bare_play_keeps_the_song_that_is_on(self):
        first_say = (await self.player.command("播放"))["say"]  # nothing yet: anything
        first = self.player.current
        self.assertEqual(first_say, f"好的，先放{first.artist}的{first.title}。" if first.artist
                         else f"好的，先放{first.title}。")
        self.assertEqual(await self.player.command("播放"), {"handled": True, "say": "", "end": True})
        self.assertIs(self.player.current, first)
        self.assertEqual(len(self.speaker.started()), 1)

    async def test_explicit_stop_works_even_when_nothing_plays(self):
        self.assertTrue((await self.player.command("暂停音乐"))["handled"])
        self.assertIn("killall xqmusic", self.speaker.scripts[-1])

    async def test_next_previous_and_what_is_playing(self):
        await self.player.command("放梁静茹的歌")
        first = self.player.current
        await self.player.command("下一首")
        self.assertIsNot(self.player.current, first)
        self.assertEqual(len(self.speaker.started()), 2)
        await self.player.command("上一首")
        self.assertIs(self.player.current, first)
        result = await self.player.command("这是什么歌")
        self.assertEqual(result["say"], f"这是{first.artist}的{first.title}。")

    async def test_the_next_song_follows_when_one_ends(self):
        await self.player.command("放梁静茹的歌")
        first = self.player.current
        self.clock.now += 200
        self.speaker.end(self.player.pid)
        await self.settle()
        self.assertEqual(len(self.speaker.started()), 2)
        self.assertIsNot(self.player.current, first)

    async def test_repeat_one_plays_the_same_song_again(self):
        await self.player.command("放梁静茹的歌")
        await self.player.command("单曲循环")
        first = self.player.current
        self.clock.now += 200
        self.speaker.end(self.player.pid)
        await self.settle()
        self.assertIs(self.player.current, first)
        self.assertEqual(len(self.speaker.started()), 2)

    async def test_songs_that_fail_at_once_are_skipped_then_given_up(self):
        await self.player.command("放梁静茹的歌")
        for _ in range(3):
            self.speaker.end(self.player.pid)
            await self.settle()
        self.assertFalse(self.player.playing)
        self.assertEqual(len(self.speaker.started()), 3)

    async def test_ducking_turns_down_only_the_music(self):
        await self.player.command("播放梁静茹的勇气")
        await self.player.duck()
        self.assertEqual(self.speaker.volumes()[-1], softvol(20))
        self.assertEqual(softvol(20), 155)
        # A song started while ducked starts quiet.
        await self.player.command("下一首")
        self.assertIn(f"cset name=xqmusicvol {softvol(20)}", self.speaker.started()[-1])
        await self.player.unduck()
        self.assertEqual(self.speaker.volumes()[-1], 255)
        self.assertFalse(self.player.ducked)

    async def test_watchdog_restores_the_music_without_a_conversation(self):
        await self.player.command("播放梁静茹的勇气")
        await self.player.duck()
        watchdog = asyncio.create_task(self.player.watchdog(interval=0.01))
        self.addCleanup(watchdog.cancel)
        self.active = True
        self.clock.now += 60
        await asyncio.sleep(0.05)
        self.assertTrue(self.player.ducked)  # a conversation keeps it down
        self.active = False
        await asyncio.sleep(0.05)
        self.assertFalse(self.player.ducked)


class ServerTests(unittest.TestCase):
    def test_byte_ranges(self):
        self.assertIsNone(byte_range(None, 100))
        self.assertEqual(byte_range("bytes=0-", 100), (0, 99))
        self.assertEqual(byte_range("bytes=10-19", 100), (10, 19))
        self.assertEqual(byte_range("bytes=-10", 100), (90, 99))
        self.assertEqual(byte_range("bytes=50-500", 100), (50, 99))
        self.assertIs(byte_range("bytes=100-", 100), False)

    def test_mp3_resumes_from_the_frames_at_that_second(self):
        track = SimpleNamespace(ext="mp3", duration=100.0, audio_start=1000, audio_end=101000)
        self.assertEqual(track_span(track, 101128, 0), (0, 101128))
        self.assertEqual(track_span(track, 101128, 50), (51000, 101000))
        flac = SimpleNamespace(ext="flac", duration=100.0, audio_start=None, audio_end=None)
        self.assertEqual(track_span(flac, 5000, 50), (0, 5000))


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_serves_files_and_requests(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "梁静茹"))
            with open(os.path.join(root, "梁静茹", "勇气.mp3"), "wb") as f:
                f.write(bytes(range(256)) * 4)
            speaker = FakeSpeaker()
            ended = Mock()
            settings = MusicSettings(enabled=True, library=root, http_port=0, index_path="")
            service = MusicService(settings, asyncio.get_running_loop(), speaker, end_after_reply=ended)
            service.library.scan()
            from xiaozhi.services.music import server
            httpd = server.serve(service, 0)
            self.addCleanup(httpd.server_close)
            self.addCleanup(httpd.shutdown)
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            track = service.library.tracks[0]

            def get(path, headers=None, data=None):
                request = urllib.request.Request(base + path, headers=headers or {}, data=data)
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, response.read()

            loop = asyncio.get_running_loop()
            status, body = await loop.run_in_executor(None, get, f"/music/track/{track.id}.mp3")
            self.assertEqual((status, len(body)), (200, 1024))
            status, body = await loop.run_in_executor(
                None, lambda: get(f"/music/track/{track.id}.mp3", {"Range": "bytes=10-19"}))
            self.assertEqual((status, body), (206, bytes(range(10, 20))))
            with patch("xiaozhi.services.music.player.HEALTH"):
                status, body = await loop.run_in_executor(
                    None, lambda: get("/music/command", {"Content-Type": "application/json"},
                                      json.dumps({"text": "播放勇气"}).encode()))
                result = json.loads(body)
                self.assertEqual(result["say"], "好的，梁静茹的勇气。")
                ended.assert_called_once()
                status, body = await loop.run_in_executor(
                    None, lambda: get("/music/command", {}, json.dumps({"text": "今天天气怎么样"}).encode()))
                self.assertFalse(json.loads(body)["handled"])
                self.assertEqual(ended.call_count, 1)
                status, body = await loop.run_in_executor(None, get, "/music/status")
                self.assertTrue(json.loads(body)["playing"])
                status, body = await loop.run_in_executor(None, get, "/music/search?q=%E5%8B%87%E6%B0%94")
                self.assertEqual(json.loads(body)["title"], "勇气")
            for task in list(service.player._tasks):
                task.cancel()


class JsonSpeaker(FakeSpeaker):
    """Like XiaoAI.run_shell: the client's result as a JSON string."""

    async def __call__(self, script, timeout=10000):
        result = await super().__call__(script, timeout)
        return json.dumps({"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code})


class RealShellTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_bridge_shell_answers_in_json(self):
        speaker = JsonSpeaker()
        service = MusicService(MusicSettings(enabled=True, index_path=""), asyncio.get_running_loop(), speaker)
        service.library = service.player.library = library()
        with patch("xiaozhi.services.music.player.HEALTH"):
            result = await service.player.command("放一首梁静茹的偶阵雨")
        self.assertEqual(result["say"], "好的，梁静茹的偶阵雨。")
        self.assertIn("http://192.168.5.10:4400/music/track/", speaker.started()[-1])
        self.assertTrue(service.player.playing)
        for task in list(service.player._tasks):
            task.cancel()


class SessionEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_music_stays_down_while_a_new_conversation_runs(self):
        active = [True]
        service = MusicService(MusicSettings(enabled=True, index_path=""), asyncio.get_running_loop(),
                               FakeSpeaker(), session_active=lambda: active[0])
        service.player.ducked = True
        await service.on_session_end()
        self.assertTrue(service.player.ducked)
        active[0] = False
        with patch("xiaozhi.services.music.player.HEALTH"):
            await service.on_session_end()
        self.assertFalse(service.player.ducked)


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    """The bridge turns the music down on a wake and back up when the conversation ends."""

    async def asyncSetUp(self):
        self.manager = getattr(event_module, "__EventManager")()
        with patch("xiaozhi.services.audio.kws.set_kws"):
            self.kws = _KWS()
        self.vad = SimpleNamespace(resume=Mock(), pause=Mock())
        self.xiaozhi = SimpleNamespace(
            loop=asyncio.get_running_loop(), device_state=DeviceState.IDLE,
            abort_tts_output=AsyncMock(),
            protocol=SimpleNamespace(send_abort_speaking=AsyncMock()),
        )
        self.xiaozhi.set_device_state = lambda state: setattr(self.xiaozhi, "device_state", state)
        self.music = SimpleNamespace(on_wake=AsyncMock(), on_session_end=AsyncMock())
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {"get_env": "1", "get_xiaozhi": self.xiaozhi, "get_vad": self.vad,
                            "get_kws": self.kws, "get_audio_codec": object(), "get_speaker": object(),
                            "get_music": self.music}.items():
            self.stack.enter_context(patch(f"xiaozhi.event.{name}", return_value=value))
        self.stack.enter_context(patch("xiaozhi.event.HEALTH"))
        self.stack.enter_context(patch.dict(event_module.APP_CONFIG["vad"], {"tts_end_guard_ms": 0}))
        self.goodbye = AsyncMock()
        self.stack.enter_context(patch.dict(event_module.APP_CONFIG["wakeup"], {
            "timeout": 0.01, "exit_guard_ms": 0, "after_wakeup": self.goodbye}))

    async def test_wake_word_turns_the_music_down_before_the_prompt(self):
        order = []
        self.music.on_wake.side_effect = lambda: order.append("duck")

        async def before_wakeup(speaker, text, source):
            order.append("prompt")
            return False

        with patch.dict(event_module.APP_CONFIG["wakeup"], {"before_wakeup": before_wakeup}):
            await self.manager.wakeup("你好小七", "kws")
            self.assertEqual(order, ["duck", "prompt"])
            await self.manager.wakeup("播放音乐", "xiaoai")
        self.music.on_wake.assert_awaited_once()

    async def test_answer_to_a_music_request_ends_the_conversation_quietly(self):
        self.manager._set_step(Step.on_wakeup, new_session=True)
        self.manager.request_end_after_reply()
        self.manager._set_step(Step.on_tts_end, new_session=True)
        await self.manager._EventManager__start_session(self.manager.session_id, Step.on_tts_end)
        await asyncio.sleep(0)
        self.goodbye.assert_not_awaited()
        self.assertEqual(self.manager.current_step, Step.idle)
        self.music.on_session_end.assert_awaited_once()
        self.vad.resume.assert_not_called()

    async def test_a_new_wake_forgets_an_unanswered_music_request(self):
        self.manager.request_end_after_reply()
        self.manager._set_step(Step.on_wakeup, new_session=True)
        task = asyncio.create_task(
            self.manager._EventManager__start_session(self.manager.session_id, Step.on_wakeup))
        await asyncio.sleep(0.05)
        await task
        await asyncio.sleep(0)
        self.assertFalse(self.manager.end_after_reply)
        self.goodbye.assert_awaited_once()  # ended by the timeout, as usual
        self.music.on_session_end.assert_awaited()

    async def test_session_active(self):
        self.assertFalse(self.manager.session_active())
        self.manager._set_step(Step.on_wakeup, new_session=True)
        self.assertTrue(self.manager.session_active())
        self.manager._set_step(Step.on_interrupt, new_session=True)
        self.assertFalse(self.manager.session_active())


if __name__ == "__main__":
    unittest.main()
