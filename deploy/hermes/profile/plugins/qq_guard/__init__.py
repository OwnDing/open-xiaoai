"""qq_guard: QQ private chats go through the speaker's tool-call guard.

A message from QQ normally reaches Hermes' agent directly, without the checks
the speaker's xiaozhi provider (deploy/hermes/xiaozhi-provider/hermes.py) runs
around it. This plugin answers a paired user's plain text message itself, with
that same provider:

- saved scene phrases and music requests run without the model;
- a reply that says a device was switched, a rule saved or a state read, with
  no tool call behind it this turn, is dropped and the request retried once
  with a reminder (then "这次没有真正执行成功……");
- device, history and TV questions must call their tools.

The provider talks to Hermes' own API server (stateless chat completions with
the conversation so far, like the speaker), so these turns are api_server
sessions. The plugin keeps the last few QQ turns per chat as that history.

Everything else is left to Hermes (return None): other platforms, groups,
slash commands, images/voice/files, unpaired senders (they still get the
pairing flow), and any turn the provider fails on.

Files: hermes.py is copied next to this file by install.sh; scene_run.py and
ha.py are read from $HERMES_HOME/mcp/home_rules (installed for the MCP server).
"""

import asyncio
import importlib.util
import json
import logging
import os
import sys
import threading
import time
import types
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("hermes_plugins.qq_guard")

HERE = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
HISTORY_FILE = HERMES_HOME / "qq_guard_history.json"
KEEP_MESSAGES = 12  # the last six exchanges
IDLE_RESET_S = 30 * 60  # a new conversation after half an hour of quiet
WEEKDAYS = "一二三四五六日"

# Replies for QQ instead of the speaker's "你再说一遍吧".
PROVIDER_CONFIG = {
    "base_url": "http://127.0.0.1:8642/v1",
    "model_name": "xiaoqi-home",
    "search_filler": "",
    "search_failed_reply": "这次没查到，你再问我一次吧。",
    "claim_failed_reply": "这次没有真正执行成功，你再发一遍吧。",
    "state_failed_reply": "这次没查到设备现在的状态，你再问我一次吧。",
    "save_failed_reply": "这次没有保存成功，你再发一遍吧。",
    "music_url": "http://host.docker.internal:4400",
    "timeout": {"connect": 3.0, "read": 120.0},
}
EMPTY_REPLY = "这次没有得到回答，你再发一遍吧。"


class _LoguruStyle:
    """The provider logs like loguru: logger.bind(tag=...).warning(...)."""

    def bind(self, **_):
        return self

    def __getattr__(self, level):
        return getattr(logger, level)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_provider_module(provider_path=HERE / "hermes.py", home_rules=HERMES_HOME / "mcp" / "home_rules"):
    """hermes.py with xiaozhi-server's two imports stubbed and home_rules' scene_run/ha."""
    stubs = {
        "config": types.ModuleType("config"),
        "config.logger": types.SimpleNamespace(setup_logging=lambda: _LoguruStyle()),
        "core": types.ModuleType("core"),
        "core.providers": types.ModuleType("core.providers"),
        "core.providers.llm": types.ModuleType("core.providers.llm"),
        "core.providers.llm.base": types.SimpleNamespace(LLMProviderBase=object),
        "ha": _load_module("qq_guard_ha", home_rules / "ha.py"),
        "scene_run": _load_module("qq_guard_scene_run", home_rules / "scene_run.py"),
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        return _load_module("qq_guard_provider", provider_path)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def context_message(now=None):
    """The real-time facts the speaker's xiaozhi sends, for a QQ chat."""
    now = now or datetime.now()
    return {"role": "system", "content": (
        "<context>\n"
        f"- Current time: {now:%H:%M}\n"
        f"- Today's date: {now:%Y-%m-%d} 星期{WEEKDAYS[now.weekday()]}\n"
        "- Device room: 不在任何房间——这是主人在 QQ 私聊里发来的文字消息，人可能不在家；"
        "没说房间的设备请求要先问是哪个房间\n"
        "- Reply style: QQ 文字聊天，回答会显示成文字而不是念出来，简短清楚即可\n"
        "</context>")}


class History:
    """The last turns of each QQ chat, kept across restarts."""

    def __init__(self, path=HISTORY_FILE):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.chats = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.chats = {}

    def get(self, chat_id, now=None):
        now = now or time.time()
        with self.lock:
            chat = self.chats.get(chat_id) or {}
            if now - chat.get("at", 0) > IDLE_RESET_S:
                return []
            return [dict(m) for m in chat.get("messages", [])]

    def add(self, chat_id, request, reply, now=None):
        now = now or time.time()
        with self.lock:
            messages = self.get_unlocked(chat_id, now)
            messages += [{"role": "user", "content": request}, {"role": "assistant", "content": reply}]
            self.chats[chat_id] = {"at": now, "messages": messages[-KEEP_MESSAGES:]}
            try:
                self.path.write_text(json.dumps(self.chats, ensure_ascii=False), encoding="utf-8")
            except OSError as e:
                logger.warning("[qq_guard] history not saved: %s", e)

    def get_unlocked(self, chat_id, now):
        chat = self.chats.get(chat_id) or {}
        return [] if now - chat.get("at", 0) > IDLE_RESET_S else list(chat.get("messages", []))


def handles(event):
    """A plain text DM on QQ (not a slash command, no media)."""
    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", None)
    if platform != "qqbot" or getattr(source, "chat_type", None) != "dm":
        return False
    text = (getattr(event, "text", None) or "").strip()
    if not text or text.startswith("/") or getattr(event, "media_urls", None):
        return False
    message_type = getattr(getattr(event, "message_type", None), "value", "text")
    return str(message_type).lower() == "text"


class Guard:
    def __init__(self):
        self._provider = None
        self._failed_at = 0.0
        self.history = History()
        self.locks = {}

    def provider(self):
        if self._provider is None and time.monotonic() - self._failed_at > 60:
            try:
                module = load_provider_module()
                config = dict(PROVIDER_CONFIG, api_key=os.environ.get("API_SERVER_KEY", ""),
                              ha_url=os.environ.get("HASS_URL"), ha_token=os.environ.get("HASS_TOKEN"))
                self._provider = module.LLMProvider(config)
                logger.info("[qq_guard] voice guard loaded for QQ chats")
            except Exception:
                self._failed_at = time.monotonic()
                logger.exception("[qq_guard] could not load the voice guard; QQ goes straight to Hermes")
        return self._provider

    def answer(self, provider, chat_id, request):
        dialogue = [context_message()] + self.history.get(chat_id) + [{"role": "user", "content": request}]
        reply = "".join(part for part in provider.response(f"qq-{chat_id}", dialogue) if isinstance(part, str))
        return reply.strip()

    async def on_dispatch(self, event=None, gateway=None, **_):
        try:
            if not handles(event) or gateway is None or not gateway._is_user_authorized(event.source):
                return None
            source = event.source
            adapter = gateway._delivery_adapter_for(source)
            provider = self.provider()
            if adapter is None or provider is None:
                return None
        except Exception:
            logger.exception("[qq_guard] check failed; Hermes answers")
            return None
        chat_id, request = source.chat_id, event.text.strip()
        async with self.locks.setdefault(chat_id, asyncio.Lock()):
            try:
                await adapter.send_typing(chat_id)
            except Exception:
                pass
            started = time.monotonic()
            try:
                reply = await asyncio.to_thread(self.answer, provider, chat_id, request)
            except Exception as e:
                logger.warning("[qq_guard] guarded turn failed (%r); Hermes answers instead", e)
                return None
            reply = reply or EMPTY_REPLY
            self.history.add(chat_id, request, reply)
            result = await adapter.send(chat_id, reply, reply_to=event.message_id)
            logger.info("[qq_guard] %s -> %s (%.1fs, sent=%s)", request[:40], reply[:60],
                        time.monotonic() - started, getattr(result, "success", None))
        return {"action": "skip", "reason": "answered by qq_guard"}


_guard = Guard()


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", _guard.on_dispatch)
