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

xiaozhi also sends its own ~6.5k-character system prompt, written for its
built-in tools (play_music, hass, get_weather, handle_exit_intent) and a
cached weather report that tells the model never to look weather up. With
Hermes that prompt conflicts with SOUL.md and made the model repeat a stale
"城市没找到" weather error, so only its real-time facts are forwarded.
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
    "稍等", "稍等一下", "等一下", "我再查一下", "我再查查", "我再看一下", "我再看看",
    "我再搜一下", "我帮你再查一下",
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
# Questions about a device's *current* state must be answered from Home
# Assistant, not from chat history or memory ("按我这边记录……").
STATE_SUBJECTS = re.compile(DEVICE_WORDS.pattern + r"|温度|湿度|漏水|水浸|窗户|门窗")
STATE_ASK = re.compile(
    r"开着|关着|亮着|灭着|开没开|关没关|是不是开|是不是关|有没有开|有没有关|几盏"
    r"|哪些.{0,4}(开|亮)|状态|现在.{0,6}(温度|湿度|多少度)|漏水|几点.{0,6}(开|关)"
    r"|什么时候.{0,6}(开|关)"
)
# Preferences are answered from memory ("我睡觉空调一般开几度").
PREFERENCE_WORDS = re.compile(r"应该|习惯|一般|喜欢|平时|合适|最好|怎么设|设多少")
STATE_RETRY_NOTE = (
    "（系统提示：这是询问设备当前状态的问题，但你上一次没有查询就回答了。"
    "聊天记录和记忆里的状态可能早已过时，现在必须调用 ha_get_state 或 ha_list_entities "
    "查询后再回答。）"
)
RETRY_NOTE = (
    "（系统提示：这是设备控制请求，但你上一次没有调用任何工具就回答了。"
    "现在必须调用 ha_call_service 真正执行，需要确认状态时调用 ha_get_state，"
    "再根据工具结果回答。不要照抄聊天记录里以前的回答。）"
)


CONTEXT_BLOCK = re.compile(r"<context>(.*?)</context>", re.S)
# xiaozhi refreshes the time on every call; Hermes knows the date but not the
# time of day or the device's city. Its weather line is deliberately dropped.
KEPT_CONTEXT = ("Current time", "Today's date", "Today's lunar date", "Device location")


def slim_system_prompt(content):
    """Keep only the real-time facts of xiaozhi's system prompt (or None)."""
    match = CONTEXT_BLOCK.search(content if isinstance(content, str) else "")
    if not match:
        return None
    facts = [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip().startswith("- ")
        and line.strip()[2:].split(":", 1)[0].strip() in KEPT_CONTEXT
    ]
    return "语音设备提供的实时信息：\n" + "\n".join(facts) if facts else None


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


def is_state_question(text):
    return bool(
        STATE_SUBJECTS.search(text)
        and STATE_ASK.search(text)
        and not PREFERENCE_WORDS.search(text)
        and not is_control_request(text)
    )


def _spoken(text):
    """Letters, digits and CJK only: drops punctuation, whitespace and emoji."""
    return re.sub(r"[\W_]", "", text)


CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN_WORDS = re.compile(r"[A-Za-z]{2,}")


def _drop_english_lead_in(text):
    """Remove an English sentence before the first Chinese character.

    Given tools, the model sometimes narrates first ("I'll check the lights.");
    the speaker must not read that. Mixed Chinese sentences are kept.
    """
    first = CJK.search(text)
    if not first:
        return text
    prefix = text[: first.start()].strip()
    # A real sentence ends with punctuation; "Apple Watch S11 缺货" is kept.
    is_sentence = len(LATIN_WORDS.findall(prefix)) >= 2 and prefix[-1:] in ".!?:"
    return text[first.start():] if is_sentence else text


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
        self.slim_system_prompt = str(config.get("slim_system_prompt", True)).lower() not in ("false", "0", "no")
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
            if not CJK.search(held) and LATIN_WORDS.search(held):
                continue  # possibly an English lead-in; wait for Chinese or a tool
            held = _drop_english_lead_in(held)
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
        if self.slim_system_prompt:
            slimmed = []
            for message in dialogue:
                if message.get("role") == "system":
                    content = slim_system_prompt(message["content"])
                    if content is None:
                        continue
                    message["content"] = content
                slimmed.append(message)
            dialogue = slimmed
        users = [m for m in dialogue if m.get("role") == "user"]
        request = _message_text(users[-1]) if users else ""

        if self.tool_guard and is_control_request(request):
            required, note, reason = None, RETRY_NOTE, "设备控制请求未调用工具"
        elif self.tool_guard and is_state_question(request):
            required, note, reason = "ha_", STATE_RETRY_NOTE, "设备状态问题未查询"
        else:
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

        # Hold the reply until the required tool runs (any tool for commands,
        # a Home Assistant tool for state questions); otherwise retry once.
        state = {"used_tool": False, "held": []}

        def guarded():
            for kind, value in self._events(dialogue):
                if kind == "tool":
                    if not state["used_tool"] and (required is None or value.startswith(required)):
                        state["used_tool"] = True
                        # Anything written before the tool is lead-in noise
                        # ("我查一下", "I'll check the lights."): drop it.
                        state["held"] = []
                elif state["used_tool"]:
                    yield value
                else:
                    state["held"].append(value)

        yield from self._clean(guarded())
        if state["used_tool"]:
            return

        held = state["held"]
        logger.bind(tag=TAG).warning(f"{reason}，已丢弃回答并重试: {request} -> {''.join(held)[:60]}")
        retry = self._events(self._with_note(dialogue, request, note))
        yield from self._clean(self._with_search_filler(retry, {"spoken": False, "held": ""}))

    @staticmethod
    def _with_note(dialogue, request, note):
        retry = [dict(message) for message in dialogue]
        last_user = max(i for i, message in enumerate(retry) if message.get("role") == "user")
        retry[last_user]["content"] = f"{request}\n{note}"
        return retry

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        for token in self.response(session_id, dialogue, **kwargs):
            yield token, None
