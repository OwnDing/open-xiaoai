"""Voice-taught scenes (HA scripts) and linkages (HA automations).

The agent describes a scene or a linkage in a small fixed vocabulary (see
README.md); this module checks it against the live Home Assistant entities
and services, applies the risk tiers and translates it into HA configuration.
Only objects whose id starts with SCENE_PREFIX / RULE_PREFIX are listed,
changed or deleted, so the user's own automations and scripts are never
touched. Pure functions: callers pass in /api/states and /api/services.
"""

import re
import uuid

SCENE_PREFIX = "xiaoqi_scene_"
RULE_PREFIX = "xiaoqi_rule_"
ANNOUNCE_SCRIPT = "xiaoqi_announce"
SCENE_ALIAS = "小七场景："
RULE_ALIAS = "小七联动："
CREATED_BY = "由小七根据语音创建："
# A one-shot linkage ("这次洗完提醒我") switches itself off after running and is
# deleted the next time the list is read.
ONCE_MARK = "（一次性）"

# Devices a scene or linkage may switch. notify/script/automation/scene and
# anything that runs commands are not devices: announcements and scenes have
# their own action types.
DEVICE_DOMAINS = {
    "light", "switch", "fan", "climate", "cover", "media_player", "humidifier",
    "vacuum", "select", "number", "button", "input_boolean", "input_number",
    "input_select", "water_heater", "lock", "valve",
}
DEFAULT_RISK = {
    # Never in a scene or linkage: they run without anyone confirming.
    "high": {
        "domains": ["lock", "water_heater", "valve", "alarm_control_panel"],
        "keywords": ["门锁", "燃气", "煤气", "热水器", "取暖", "暖风", "电暖", "地暖", "暖气"],
    },
    # Allowed, but a linkage that switches them must also announce it.
    "medium": {
        "domains": ["climate", "cover", "media_player", "humidifier", "vacuum"],
        "keywords": ["空调", "窗帘", "电视"],
    },
}
# Triggers whose announcements may break the quiet hours.
SAFETY_DEVICE_CLASSES = {"moisture", "smoke", "gas", "carbon_monoxide", "safety"}
SAFETY_KEYWORDS = ("水浸", "漏水", "浸没", "烟雾", "燃气", "煤气")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_ACTIONS = 20
MAX_DELAY_S = 3600


def _name_of(state):
    return state.get("attributes", {}).get("friendly_name") or state["entity_id"]


def risk_of(state, risk=None):
    risk = risk or DEFAULT_RISK
    domain = state["entity_id"].split(".", 1)[0]
    name = _name_of(state)
    for tier in ("high", "medium"):
        cfg = risk.get(tier, {})
        if domain in cfg.get("domains", ()) or any(k in name for k in cfg.get("keywords", ())):
            return tier
    return "low"


def is_safety_sensor(state):
    attrs = state.get("attributes", {})
    return attrs.get("device_class") in SAFETY_DEVICE_CLASSES or any(
        k in _name_of(state) for k in SAFETY_KEYWORDS
    )


def _hhmmss(value):
    match = HHMM.match(str(value or "").strip())
    return f"{int(match.group(1)):02d}:{match.group(2)}:00" if match else None


def _is_number(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


class Checker:
    """Collects problems (in Chinese, for the agent to relay or fix)."""

    def __init__(self, states, services, risk=None):
        self.states = {s["entity_id"]: s for s in states}
        self.services = services
        self.risk = risk or DEFAULT_RISK
        self.problems = []

    def entity(self, entity_id, what):
        state = self.states.get(entity_id or "")
        if state is None:
            self.problems.append(f"{what}的实体 {entity_id} 不存在，请先用 ha_list_entities 查到准确的实体 ID")
        return state

    def state_value(self, state, value, what):
        """Binary sensors take on/off; entities with listed options take one of them."""
        if value is None or state is None:
            return
        domain = state["entity_id"].split(".", 1)[0]
        options = state.get("attributes", {}).get("options")
        if domain == "binary_sensor" and value not in ("on", "off"):
            self.problems.append(f"{what}：{_name_of(state)} 的状态只有 on 和 off（门开、漏水、运行中都是 on）")
        elif options and value not in options:
            self.problems.append(f"{what}：{_name_of(state)} 的状态只能是 {'、'.join(map(str, options))} 之一")


def _trigger(t, check):
    kind = t.get("type")
    if kind == "state":
        state = check.entity(t.get("entity_id"), "触发条件")
        check.state_value(state, t.get("to"), "触发条件")
        check.state_value(state, t.get("from"), "触发条件")
        out = {"trigger": "state", "entity_id": t.get("entity_id")}
        for key in ("to", "from"):
            if t.get(key) is not None:
                out[key] = str(t[key])
        if "to" not in out and "from" not in out:
            # Only real changes, not attribute updates or unavailable blips.
            out["not_from"] = ["unavailable", "unknown"]
            out["not_to"] = ["unavailable", "unknown"]
    elif kind == "numeric":
        state = check.entity(t.get("entity_id"), "触发条件")
        if state is not None and not _is_number(state.get("state")):
            check.problems.append(f"触发条件：{_name_of(state)} 不是数值，不能用 above/below")
        if t.get("above") is None and t.get("below") is None:
            check.problems.append("数值触发需要 above 或 below")
        out = {"trigger": "numeric_state", "entity_id": t.get("entity_id")}
        for key in ("above", "below"):
            if t.get(key) is not None:
                out[key] = float(t[key])
    elif kind == "event":
        state = check.entity(t.get("entity_id"), "触发条件")
        if state is not None and not state["entity_id"].startswith("event."):
            check.problems.append(f"事件触发要用 event. 开头的实体，{_name_of(state)} 不是事件")
        # An event entity's state is the time of its last event: any change is a new event.
        out = {"trigger": "state", "entity_id": t.get("entity_id"),
               "not_from": ["unavailable"], "not_to": ["unavailable", "unknown"]}
    elif kind == "time":
        at = _hhmmss(t.get("at"))
        if at is None:
            check.problems.append("时间触发的 at 要写成 HH:MM，例如 22:30")
        out = {"trigger": "time", "at": at}
        return out, _weekday_condition(t.get("weekdays"), check)
    else:
        check.problems.append("触发条件的 type 只能是 state、numeric、event、time")
        return None, None
    seconds = t.get("for_seconds")
    if seconds:
        if not _is_number(seconds) or int(seconds) < 0:
            check.problems.append("for_seconds 要是不小于 0 的整数")
        else:
            out["for"] = {"seconds": int(seconds)}
    return out, None


def _weekday_condition(days, check):
    if not days:
        return None
    bad = [d for d in days if d not in WEEKDAYS]
    if bad:
        check.problems.append(f"weekdays 只能用 {'、'.join(WEEKDAYS)}")
        return None
    return {"condition": "time", "weekday": list(days)}


def _condition(c, check):
    kind = c.get("type")
    if kind == "state":
        state = check.entity(c.get("entity_id"), "限制条件")
        check.state_value(state, c.get("state"), "限制条件")
        if c.get("state") is None:
            check.problems.append("状态限制条件需要 state")
        return {"condition": "state", "entity_id": c.get("entity_id"), "state": str(c.get("state"))}
    if kind == "numeric":
        state = check.entity(c.get("entity_id"), "限制条件")
        if state is not None and not _is_number(state.get("state")):
            check.problems.append(f"限制条件：{_name_of(state)} 不是数值，不能用 above/below")
        if c.get("above") is None and c.get("below") is None:
            check.problems.append("数值限制条件需要 above 或 below")
        out = {"condition": "numeric_state", "entity_id": c.get("entity_id")}
        for key in ("above", "below"):
            if c.get(key) is not None:
                out[key] = float(c[key])
        return out
    if kind == "time":
        out = {"condition": "time"}
        for key in ("after", "before"):
            if c.get(key) is not None:
                value = _hhmmss(c[key])
                if value is None:
                    check.problems.append(f"时间限制条件的 {key} 要写成 HH:MM")
                out[key] = value
        weekday = _weekday_condition(c.get("weekdays"), check)
        if weekday:
            out["weekday"] = weekday["weekday"]
        if len(out) == 1:
            check.problems.append("时间限制条件需要 after、before 或 weekdays")
        return out
    check.problems.append("限制条件的 type 只能是 state、numeric、time")
    return None


def _action(a, check, scenes, own_name, urgent_allowed):
    """Returns (HA action, risk tier of a device action or None, is announce)."""
    kind = a.get("type")
    if kind == "device":
        state = check.entity(a.get("entity_id"), "动作")
        service = str(a.get("service") or "")
        if state is None:
            return None, None, False
        domain = state["entity_id"].split(".", 1)[0]
        if domain not in DEVICE_DOMAINS:
            check.problems.append(f"{_name_of(state)} 不是可以控制的设备")
            return None, None, False
        if service not in check.services.get(domain, {}):
            known = "、".join(sorted(check.services.get(domain, {}))[:12])
            check.problems.append(f"{_name_of(state)} 没有 {service} 这个操作，可用的有：{known}")
        tier = risk_of(state, check.risk)
        if tier == "high":
            check.problems.append(f"{_name_of(state)} 是高风险设备，不能放进场景或联动，请让用户需要时直接说")
        out = {"action": f"{domain}.{service}", "target": {"entity_id": state["entity_id"]}}
        if a.get("data"):
            if not isinstance(a["data"], dict):
                check.problems.append("动作的 data 要是对象，例如 {\"temperature\": 26}")
            else:
                out["data"] = a["data"]
        return out, tier, False
    if kind == "announce":
        message = str(a.get("message") or "").strip()
        if not message or len(message) > 200:
            check.problems.append("播报内容不能为空，也不要超过 200 字")
        urgent = bool(a.get("urgent"))
        if urgent and not urgent_allowed:
            check.problems.append("只有漏水、烟雾、燃气这类安全报警的联动才能在勿扰时段播报，其他播报请去掉 urgent")
        return {"action": f"script.{ANNOUNCE_SCRIPT}", "data": {"message": message, "urgent": urgent}}, None, True
    if kind == "scene":
        name = str(a.get("scene") or "").strip()
        target = scenes.get(name)
        if name == own_name:
            check.problems.append("场景不能调用它自己")
        elif target is None:
            check.problems.append(f"没有叫“{name}”的场景，已有：{'、'.join(scenes) or '（没有）'}")
        return ({"action": f"script.{target}"} if target else None), None, False
    if kind == "delay":
        seconds = a.get("seconds")
        if not _is_number(seconds) or not 1 <= int(seconds) <= MAX_DELAY_S:
            check.problems.append(f"等待时间 seconds 要在 1 到 {MAX_DELAY_S} 之间")
            return None, None, False
        return {"delay": {"seconds": int(seconds)}}, None, False
    check.problems.append("动作的 type 只能是 device、announce、scene、delay")
    return None, None, False


def build(kind, name, actions, states, services, trigger=None, conditions=None,
          summary="", scenes=None, risk=None, once=False):
    """Returns (HA config, problems). scenes maps saved scene names to script object ids."""
    check = Checker(states, services, risk)
    scenes = scenes or {}
    name = str(name or "").strip()
    if not name or len(name) > 30:
        check.problems.append("名字不能为空，也不要超过 30 个字")
    if kind not in ("scene", "rule"):
        check.problems.append("kind 只能是 scene（场景）或 rule（联动）")
        return None, check.problems
    actions = list(actions or [])
    if not actions:
        check.problems.append("至少要有一个动作")
    if len(actions) > MAX_ACTIONS:
        check.problems.append(f"动作太多了，最多 {MAX_ACTIONS} 个")

    ha_trigger, extra_condition, urgent_allowed = None, None, False
    if kind == "rule":
        if not trigger:
            check.problems.append("联动需要一个触发条件（trigger）")
        else:
            ha_trigger, extra_condition = _trigger(trigger, check)
            source = check.states.get(trigger.get("entity_id") or "")
            urgent_allowed = source is not None and is_safety_sensor(source)
    elif trigger or conditions:
        check.problems.append("场景由用户说口令来执行，不需要触发条件和限制条件")

    ha_conditions = [extra_condition] if extra_condition else []
    for c in (conditions or []) if kind == "rule" else []:
        out = _condition(c, check)
        if out:
            ha_conditions.append(out)

    ha_actions, medium, announces = [], False, False
    for a in actions:
        out, tier, is_announce = _action(a, check, scenes, name, urgent_allowed)
        if out:
            ha_actions.append(out)
        medium = medium or tier == "medium"
        announces = announces or is_announce
    if kind == "rule" and medium and not announces:
        check.problems.append("联动里有空调、窗帘、电视这类中风险设备，需要再加一条 announce 播报说明做了什么")
    if check.problems:
        return None, check.problems

    description = CREATED_BY + (ONCE_MARK if kind == "rule" and once else "") + (str(summary).strip() or name)
    if kind == "rule" and once:
        ha_actions.append({"action": "automation.turn_off", "target": {"entity_id": "{{ this.entity_id }}"}})
    if kind == "scene":
        return {"alias": SCENE_ALIAS + name, "description": description, "mode": "single",
                "sequence": ha_actions}, []
    return {"alias": RULE_ALIAS + name, "description": description, "mode": "single",
            "triggers": [ha_trigger], "conditions": ha_conditions, "actions": ha_actions}, []


BEHAVIOUR_KEYS = {"scene": ("sequence",), "rule": ("triggers", "conditions", "actions")}


def same_behaviour(kind, a, b):
    """Two configs that would do exactly the same thing, whatever their names."""
    return all((a or {}).get(k) == (b or {}).get(k) for k in BEHAVIOUR_KEYS[kind])


def is_spent(item, description):
    """A one-shot linkage that has run and switched itself off."""
    return (item["kind"] == "rule" and not item["enabled"] and item.get("last_triggered")
            and str(description or "").startswith(CREATED_BY + ONCE_MARK))


def new_id(kind):
    return (SCENE_PREFIX if kind == "scene" else RULE_PREFIX) + uuid.uuid4().hex[:10]


def owned(states):
    """Scenes and linkages created here: [{kind, id, entity_id, name, enabled, last_triggered}]."""
    items = []
    for s in states:
        entity_id, attrs = s["entity_id"], s.get("attributes", {})
        if entity_id.startswith("script." + SCENE_PREFIX):
            kind, object_id, alias = "scene", entity_id.split(".", 1)[1], SCENE_ALIAS
        elif entity_id.startswith("automation.") and str(attrs.get("id", "")).startswith(RULE_PREFIX):
            kind, object_id, alias = "rule", attrs["id"], RULE_ALIAS
        else:
            continue
        name = _name_of(s)
        items.append({
            "kind": kind, "id": object_id, "entity_id": entity_id,
            "name": name[len(alias):] if name.startswith(alias) else name,
            "enabled": s.get("state") != "off",
            "last_triggered": attrs.get("last_triggered"),
        })
    return items


def find(items, name, kind=None):
    name = str(name or "").strip()
    matches = [i for i in items if (kind is None or i["kind"] == kind) and i["name"] == name]
    if not matches:
        matches = [i for i in items if (kind is None or i["kind"] == kind) and name and name in i["name"]]
    return matches
