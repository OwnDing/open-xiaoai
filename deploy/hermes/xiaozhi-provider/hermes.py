"""xiaozhi-esp32-server LLM provider for Hermes Agent, with a tool-call guard.

Mounted into the server as core/providers/llm/hermes/hermes.py and selected
with `type: hermes` in data/.config.yaml.

xiaozhi sends the dialogue as plain text, so the model sees earlier turns in
which it "switched a light" with no visible tool call. A fast non-thinking
model sometimes copies that and answers "好了，灯关了" without calling Home
Assistant. For requests that look like device control, this provider holds
the reply back until Hermes reports a tool call (`event: hermes.tool.progress`,
which precedes any text when a tool is used). If the stream ends without one,
the reply is discarded and the request is retried once with an explicit
reminder.

Web search is slow, so the speaker says "我查一下" while it runs. Asking the
model to say that itself before calling the tool proved unreliable: it would
sometimes stop right after the filler (the turn ends in silence) or keep
talking from memory without searching. So the model now calls the tool
directly and this provider speaks the filler when Hermes reports a
web_search. A reply that merely opens with a filler is held back until it is
clear whether a search follows; a filler-only reply is retried once.
"""

import json
import re

import httpx

from config.logger import setup_logging
from core.providers.llm.base import LLMProviderBase

TAG = __name__
logger = setup_logging()

DEVICE_WORDS = re.compile(
    r"灯|风扇|空调|窗帘|电视|插座|开关|加湿器|除湿|净化器|扫地|热水器|暖气|地暖|门锁|晾衣"
)
# Explicit command phrasing only: a bare 开/关 also appears in questions such as
# "空调应该开多少度" or "灯开着吗", which must be answered, not forced into a tool.
COMMAND_WORDS = re.compile(
    r"打开|关闭|关掉|关上|关了|开开|开启|启动|停止|暂停|开一下|关一下|开下|关下"
    r"|调到|调成|调为|调高|调低|调亮|调暗|调大|调小|设为|设成|设置|切换|升起|降下"
    r"|把.{0,10}?(开|关|调|设)"
    r"|(开|关)(灯|风扇|空调|电视|窗帘|插座)"
)
# Phrases a model uses right before it (should) look something up.
FILLERS = (
    "我查一下", "我查查", "查一下", "我搜一下", "我搜搜", "搜一下", "我看一下",
    "我看看", "我帮你查一下", "我帮你查查", "我帮你看看", "让我查一下", "让我看看",
    "稍等", "稍等一下", "等一下",
)
# Openings dropped when no search follows. First-person forms only, so advice
# such as "查一下体温吧" is never cut.
DROPPABLE_OPENINGS = tuple(f for f in FILLERS if not f.startswith(("查", "搜")))
LEADING_FILLER = re.compile(
    r"^\W*(?:" + "|".join(sorted(DROPPABLE_OPENINGS, key=len, reverse=True)) + ")"
)
MAX_FILLER_CLAUSE = 12
# Where the filler clause ends. \W* in LEADING_FILLER already skips emoji.
CLAUSE_END = re.compile(r"[。！？!?；;，,：:…\n]")
SEARCH_TOOLS = ("web_search", "web_extract")
FILLER_RETRY_NOTE = (
    "（系统提示：你上一次只说了一句“我查一下”就结束了，没有真正查询。"
    "需要实时信息就直接调用 web_search 搜索后回答；不需要搜索就直接回答。）"
)
RETRY_NOTE = (
    "（系统提示：这是设备控制请求，但你上一次没有调用任何工具就回答了。"
    "现在必须调用 ha_call_service 真正执行，需要确认状态时调用 ha_get_state，"
    "再根据工具结果回答。不要照抄聊天记录里以前的回答。）"
)


def _message_text(message):
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    # xiaozhi wraps ASR output as {"content": ..., "language": ..., "emotion": ...}.
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "content" in data:
            return str(data["content"])
    except (TypeError, ValueError):
        pass
    return str(content)


def is_control_request(text):
    return bool(DEVICE_WORDS.search(text) and COMMAND_WORDS.search(text))


def _spoken(text):
    """Letters, digits and CJK only: drops punctuation, whitespace and emoji."""
    return re.sub(r"[\W_]", "", text)


def is_filler_only(text):
    return _spoken(text) in {_spoken(f) for f in FILLERS}


def _could_become_filler(text):
    spoken = _spoken(text)
    return any(_spoken(f).startswith(spoken) for f in FILLERS)


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.base_url = (config.get("base_url") or config.get("url") or "http://hermes:8642/v1").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.model_name = config.get("model_name", "xiaoqi-home")
        self.temperature = config.get("temperature")
        self.max_tokens = config.get("max_tokens")
        self.tool_guard = str(config.get("tool_guard", True)).lower() not in ("false", "0", "no")
        self.search_filler = config.get("search_filler", "我查一下。")
        self.search_failed_reply = config.get("search_failed_reply", "这次没查到，你再问我一次吧。")
        timeout = config.get("timeout") if isinstance(config.get("timeout"), dict) else {}
        self.client = httpx.Client(
            timeout=httpx.Timeout(
                connect=timeout.get("connect", 3.0),
                read=timeout.get("read", 90.0),
                write=timeout.get("write", 10.0),
                pool=timeout.get("pool", 5.0),
            )
        )

    def _events(self, dialogue):
        """Yield ("tool", name) and ("text", chunk) from Hermes' SSE stream."""
        body = {"model": self.model_name, "messages": dialogue, "stream": True}
        if self.temperature not in (None, ""):
            body["temperature"] = float(self.temperature)
        if self.max_tokens not in (None, ""):
            body["max_tokens"] = int(self.max_tokens)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        event = None
        with self.client.stream(
            "POST", f"{self.base_url}/chat/completions", json=body, headers=headers
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    event = None
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if event == "hermes.tool.progress":
                    yield "tool", data.get("tool", "")
                elif event in (None, "message"):
                    for choice in data.get("choices") or []:
                        content = (choice.get("delta") or {}).get("content")
                        if content:
                            yield "text", content

    @staticmethod
    def _clean(chunks):
        started = False
        for chunk in chunks:
            if not started:
                chunk = chunk.lstrip()
                if not chunk:
                    continue
                started = True
            yield chunk

    def _texts(self, dialogue):
        return (value for kind, value in self._events(dialogue) if kind == "text")

    def _with_search_filler(self, events, state):
        """Text of one Hermes turn, speaking our own filler when a search starts.

        state["spoken"] tells whether anything was yielded; state["held"] keeps
        a filler-looking opening that was never resolved (for the retry check).
        """
        held = ""
        deciding = True
        for kind, value in events:
            if kind == "tool":
                if deciding:
                    # The model's own "我查一下…" before the tool is dropped.
                    held = ""
                    deciding = False
                    if value in SEARCH_TOOLS and self.search_filler:
                        state["spoken"] = True
                        yield self.search_filler
                continue
            if not deciding:
                state["spoken"] = True
                yield value
                continue
            held += value
            waiting = False
            while True:
                match = LEADING_FILLER.match(held)
                if not match:
                    waiting = _could_become_filler(held)
                    break
                clause_end = CLAUSE_END.search(held, match.end())
                if not clause_end:
                    # Still inside "我查一下（今天的新闻）" — wait, unless it is
                    # clearly a real sentence rather than a filler.
                    waiting = len(_spoken(held)) <= MAX_FILLER_CLAUSE
                    break
                if len(_spoken(held[: clause_end.start()])) > MAX_FILLER_CLAUSE:
                    break
                if not _spoken(held[clause_end.end():]):
                    waiting = True
                    break
                # It kept talking without a search: drop the fake filler clause.
                held = held[clause_end.end():]
            if waiting:
                continue
            deciding = False
            if held.strip():
                state["spoken"] = True
                yield held
            held = ""
        state["held"] = held

    def response(self, session_id, dialogue, **kwargs):
        dialogue = [dict(message) for message in dialogue]
        for message in dialogue:
            message.setdefault("content", "")
        users = [m for m in dialogue if m.get("role") == "user"]
        request = _message_text(users[-1]) if users else ""

        if not (self.tool_guard and is_control_request(request)):
            state = {"spoken": False, "held": ""}
            yield from self._clean(self._with_search_filler(self._events(dialogue), state))
            if state["spoken"]:
                return
            logger.bind(tag=TAG).warning(
                f"只回复了“{state['held'].strip()[:20]}”没有真正查询，已重试: {request}"
            )
            retry_state = {"spoken": False, "held": ""}
            retry = self._with_note(dialogue, request, FILLER_RETRY_NOTE)
            yield from self._clean(self._with_search_filler(self._events(retry), retry_state))
            if not retry_state["spoken"] and self.search_failed_reply:
                yield self.search_failed_reply
            return

        state = {"used_tool": False, "held": []}

        def guarded():
            for kind, value in self._events(dialogue):
                if kind == "tool":
                    if not state["used_tool"]:
                        state["used_tool"] = True
                        yield from state["held"]
                        state["held"] = []
                elif state["used_tool"]:
                    yield value
                else:
                    state["held"].append(value)

        yield from self._clean(guarded())
        if state["used_tool"]:
            return

        held = state["held"]
        logger.bind(tag=TAG).warning(
            f"设备控制请求未调用工具，已丢弃回答并重试: {request} -> {''.join(held)[:60]}"
        )
        yield from self._clean(self._texts(self._with_note(dialogue, request, RETRY_NOTE)))

    @staticmethod
    def _with_note(dialogue, request, note):
        retry = [dict(message) for message in dialogue]
        last_user = max(i for i, message in enumerate(retry) if message.get("role") == "user")
        retry[last_user]["content"] = f"{request}\n{note}"
        return retry

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        for token in self.response(session_id, dialogue, **kwargs):
            yield token, None
