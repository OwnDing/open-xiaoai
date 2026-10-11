"""Run a voice-taught scene and report what its devices really did.

Two callers share this file, so it imports nothing from this package:
- the home_rules MCP server (`home_rule_run`, when the model runs a scene), and
- the xiaozhi Hermes provider, which runs a scene itself when the user says its
  phrase, without asking the model. The file is mounted next to
  xiaozhi-provider/hermes.py, together with ha.py.

`ha` is anything with ha.HomeAssistant's methods: request, state, get_config
and call. Every function that talks to Home Assistant may raise; run() turns
failures into an "error" result instead.
"""

import json
import re
import time

# Same as rules.SCENE_PREFIX / rules.SCENE_ALIAS (checked by the unit tests).
SCENE_OBJECT_PREFIX = "xiaoqi_scene_"
SCENE_ALIAS = "小七场景："
MAX_DEPTH = 3

# The scene scripts and their names, in one small request.
SCENES_TEMPLATE = (
    "{% set ns = namespace(items=[]) %}"
    "{% for s in states.script if s.entity_id.startswith('script." + SCENE_OBJECT_PREFIX + "') %}"
    "{% set ns.items = ns.items + [[s.entity_id, s.name]] %}"
    "{% endfor %}{{ ns.items | tojson }}"
)


def list_scenes(ha):
    """{phrase: script entity_id} of the saved scenes."""
    raw = ha.request("POST", "/api/template", {"template": SCENES_TEMPLATE}, text=True)
    scenes = {}
    for entity_id, name in json.loads(raw or "[]"):
        phrase = str(name)
        phrase = phrase[len(SCENE_ALIAS):] if phrase.startswith(SCENE_ALIAS) else phrase
        if phrase.strip():
            scenes[phrase.strip()] = entity_id
    return scenes


# ---------------------------------------------------------------- phrases

# 小七 as speech recognition writes it, optionally after a greeting.
ADDRESS = re.compile(
    r"^(?:你好|您好|嗨|嘿|哈喽|喂)?小[七琪琦棋旗奇齐祺淇期其柒骑启起气妻戚栖溪西希析息熙青清晴琴芹]"
)
INTERJECTION = re.compile(r"^(?:嗯+|啊+|哎+|唉+|诶+|欸+|喂+|好的|好吧|好|对|那个)(?=[\W_]|$)")
LEADING_PUNCT = re.compile(r"^[\W_]+")
CLAUSE_END = re.compile(r"[，,。！!？?；;]")
PARTICLES = re.compile(r"[了啦咯喽啊呀吧哦噢呢嘛哈]+$")
# Talking about a scene rather than saying it ("我回来了，这个场景开哪几盏灯",
# "我回来了以后也开空调"): left to the model.
RULE_TALK = re.compile(
    r"场景|口令|规则|联动|自动化|删|改|取消|以后|的时候|是什么|什么意思|哪些|哪几|干嘛|做什么|叫什么|记住|教你"
)


def phrase_key(text):
    """Comparable form: no punctuation or spaces, no trailing particles (我回来啦 = 我回来了 = 我回来)."""
    spoken = re.sub(r"[\W_]+", "", str(text or "")).lower()
    bare = PARTICLES.sub("", spoken)
    # "好了" must not shrink to "好", which is how people agree to things.
    return bare if len(bare) >= 2 else spoken


def strip_lead(text):
    """Drop a leading address ("小琪，", "你好小七") and interjections ("嗯，", "好，")."""
    while True:
        before = text
        text = LEADING_PUNCT.sub("", text)
        text = ADDRESS.sub("", text, count=1)
        text = INTERJECTION.sub("", text, count=1)
        if text == before:
            return text


def match(text, phrases):
    """(phrase, rest) when the user said a saved phrase, else None.

    The whole utterance must be the phrase (give or take an address, an
    interjection and particles), or its first clause must be, followed by
    something else to do ("我回来了，把空调开到二十六度"): then rest is that
    part. Anything less certain is left to the model.
    """
    text = str(text or "").strip()
    candidates = [text]
    if strip_lead(text) != text:
        candidates.append(strip_lead(text))
    for phrase in sorted(phrases, key=lambda p: len(phrase_key(p)), reverse=True):
        key = phrase_key(phrase)
        if not key:
            continue
        for candidate in candidates:
            if phrase_key(candidate) == key:
                return phrase, ""
            end = CLAUSE_END.search(candidate)
            if not end or phrase_key(candidate[: end.start()]) != key:
                continue
            rest = candidate[end.end():].strip()
            if not phrase_key(strip_lead(rest)):
                return phrase, ""  # "我回来了，小七。"
            if not RULE_TALK.search(rest):
                return phrase, rest
    return None


# ---------------------------------------------------------------- running

# Devices whose "on" is literally the state "on"; others (climate, media
# players, vacuums...) report a mode, so anything but off counts.
ON_OFF_DOMAINS = {"light", "switch", "fan", "input_boolean", "humidifier", "siren"}
NOT_OFF = "not_off"
GONE = {"unavailable", "unknown"}
WAIT_STEPS = ("delay", "wait_template", "wait_for_trigger")


def expectation(domain, service, data):
    """(states that mean it worked, spoken verb), or (None, None) when it can't be checked."""
    if service == "turn_off":
        return {"off"}, "关了"
    if service == "turn_on":
        return ({"on"} if domain in ON_OFF_DOMAINS else NOT_OFF), "开了"
    if domain == "cover" and service == "open_cover":
        return {"open", "opening"}, "打开了"
    if domain == "cover" and service == "close_cover":
        return {"closed", "closing"}, "关上了"
    if domain == "climate" and service == "set_hvac_mode" and (data or {}).get("hvac_mode"):
        mode = str(data["hvac_mode"])
        return {mode}, ("关了" if mode == "off" else "开了")
    return None, None


def satisfied(accept, state):
    if accept == NOT_OFF:
        return state not in GONE | {"off"}
    return state in accept


def _targets(step):
    found = []
    for holder in (step.get("target") or {}, step.get("data") or {}, step):
        value = holder.get("entity_id") if isinstance(holder, dict) else None
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",")]
        for entity_id in value or []:
            if isinstance(entity_id, str) and "." in entity_id and entity_id not in found:
                found.append(entity_id)
    return found


def plan(ha, scene_entity_id):
    """What to check after starting the scene.

    Returns (checks, unchecked, later): checks maps entity_id to (accepted
    states, verb) for the steps before the first wait, including those of
    scenes it runs; unchecked counts steps whose result can't be read from a
    state (set_temperature...); later is True when steps follow a wait.
    """
    checks, counts = {}, {"unchecked": 0, "later": False}

    def walk(object_id, depth):
        sequence = (ha.get_config("script", object_id) or {}).get("sequence") or []
        for step in sequence:
            if not isinstance(step, dict):
                continue
            if any(key in step for key in WAIT_STEPS):
                counts["later"] = True
                return True
            action = str(step.get("action") or step.get("service") or "")
            domain, _, service = action.partition(".")
            if domain == "script":
                # Another scene runs inline; announcements have nothing to check.
                if service.startswith(SCENE_OBJECT_PREFIX) and depth < MAX_DEPTH and walk(service, depth + 1):
                    return True
                continue
            accept, verb = expectation(domain, service, step.get("data"))
            for entity_id in _targets(step):
                if accept is None:
                    counts["unchecked"] += 1
                else:
                    checks[entity_id] = (accept, verb)  # a later step on the same device wins
        return False

    walk(scene_entity_id.split(".", 1)[1], 0)
    return checks, counts["unchecked"], counts["later"]


def spoken_name(state):
    """"客厅灯  灯" -> "客厅灯", "主卧灯 氛围灯" -> "主卧灯氛围灯" (as in ha_device_table.clean_name)."""
    name = (state.get("attributes") or {}).get("friendly_name") or state.get("entity_id", "")
    parts = str(name).replace("*", " ").split()
    if len(parts) > 1 and parts[0].endswith(parts[-1]):
        parts = parts[:-1]
    kept = []
    for part in parts:
        if part not in kept:
            kept.append(part)
    return "".join(kept)


def run(ha, scene_entity_id, verify_s=5.0, interval=0.3, clock=time.monotonic, sleep=time.sleep):
    """Start a scene, then wait until its devices are in their new state or verify_s has passed.

    Returns {"done": [(name, verb)], "failed": [name], "unchecked": n,
    "later": bool, "error": None or a message}. A device that already was in
    the requested state counts as done: that is what the user sees.
    """
    result = {"done": [], "failed": [], "unchecked": 0, "later": False, "error": None}
    try:
        checks, result["unchecked"], result["later"] = plan(ha, scene_entity_id)
    except Exception:  # Unreadable config: still run it, just don't check.
        checks, result["unchecked"] = {}, 1
    try:
        # script.turn_on returns at once; a scene with waits keeps running in HA.
        ha.call("script", "turn_on", {"entity_id": scene_entity_id})
        deadline = clock() + verify_s
        states = {}
        while True:
            for entity_id, (accept, _) in checks.items():
                if entity_id not in states or not satisfied(accept, states[entity_id].get("state")):
                    states[entity_id] = ha.state(entity_id) or {"entity_id": entity_id}
            if all(satisfied(accept, states[e].get("state")) or states[e].get("state") in GONE
                   for e, (accept, _) in checks.items()) or clock() >= deadline:
                break
            sleep(interval)
    except Exception as e:
        result["error"] = str(e) or e.__class__.__name__
        return result
    for entity_id, (accept, verb) in checks.items():
        state = states[entity_id]
        if satisfied(accept, state.get("state")):
            result["done"].append((spoken_name(state), verb))
        else:
            result["failed"].append(spoken_name(state))
    return result


# ---------------------------------------------------------------- replies

DEFAULT_REPLIES = {
    "done": "好，{done}。",
    "partial": "{done}，但{failed}没有反应。",
    "failed": "{failed}没有反应，“{scene}”没有执行成功。",
    "ran": "好，“{scene}”执行了。",
    "error": "现在连不上家里的设备，“{scene}”没有执行。",
    "later": "后面的动作会按设定的时间接着执行。",
}


def join_names(names):
    names = list(dict.fromkeys(names))
    if len(names) <= 1:
        return "".join(names)
    return "、".join(names[:-1]) + "和" + names[-1]


def describe(done):
    """[("客厅灯", "开了"), ("餐厅灯", "开了"), ("走廊灯", "关了")] -> "客厅灯和餐厅灯开了，走廊灯关了"."""
    groups = {}
    for name, verb in done:
        groups.setdefault(verb, []).append(name)
    return "，".join(join_names(names) + verb for verb, names in groups.items())


def reply(scene, result, templates=None):
    """The sentence to speak, from the configurable templates (see DEFAULT_REPLIES)."""
    if result["error"]:
        kind = "error"
    elif result["failed"]:
        kind = "partial" if result["done"] else "failed"
    else:
        kind = "done" if result["done"] else "ran"
    values = {"scene": scene, "done": describe(result["done"]), "failed": join_names(result["failed"])}
    templates = templates or {}
    try:
        text = str(templates.get(kind) or DEFAULT_REPLIES[kind]).format(**values)
    except (KeyError, IndexError, ValueError):  # a template with an unknown placeholder
        text = DEFAULT_REPLIES[kind].format(**values)
    if result["later"] and not result["error"]:
        text += str(templates.get("later", DEFAULT_REPLIES["later"]))
    return text
