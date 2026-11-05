"""MCP server "home_rules": voice-taught scenes and linkages for 小七.

    python -m home_rules.server            # stdio, started by Hermes (mcp_servers)
    python -m home_rules.server --install  # only (re)install script.xiaoqi_announce

Needs HASS_URL and HASS_TOKEN. Scenes become HA scripts and linkages HA
automations, so they run inside Home Assistant whether or not Hermes is up.
"""

import os
import sys
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer

from . import announce, pending, rules, scene_index, scene_run
from .ha import HAError, HomeAssistant

SOUL_PATH = os.environ.get("SOUL_PATH", "/opt/data/SOUL.md")
PENDING = pending.Pending(os.environ.get("HOME_RULES_PENDING", "/opt/data/home_rules_pending.json"))


class Trigger(BaseModel):
    type: Literal["state", "numeric", "event", "time"] = Field(
        description="state: an entity changes (door opens, leak detected, washer stops); "
                    "numeric: a value goes above/below; event: a button/switch event entity fires "
                    "(each click type is its own event.* entity); time: every day at a time")
    entity_id: Optional[str] = Field(None, description="Entity that triggers (state/numeric/event)")
    to: Optional[str] = Field(None, description="state: new state, e.g. on/off (binary sensors: door open, leak, running = on)")
    from_state: Optional[str] = Field(None, alias="from", description="state: previous state, e.g. on")
    above: Optional[float] = Field(None, description="numeric: fire when the value rises above this")
    below: Optional[float] = Field(None, description="numeric: fire when the value drops below this")
    for_seconds: Optional[int] = Field(None, description="state/numeric: only after it stayed so this long")
    at: Optional[str] = Field(None, description="time: HH:MM")
    weekdays: Optional[list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]] = Field(
        None, description="time: only on these days")

    model_config = {"populate_by_name": True}


class Condition(BaseModel):
    type: Literal["state", "numeric", "time"]
    entity_id: Optional[str] = None
    state: Optional[str] = Field(None, description="state: required current state, e.g. on/off")
    above: Optional[float] = None
    below: Optional[float] = None
    after: Optional[str] = Field(None, description="time: HH:MM")
    before: Optional[str] = Field(None, description="time: HH:MM")
    weekdays: Optional[list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]] = None


class Action(BaseModel):
    type: Literal["device", "announce", "scene", "delay"] = Field(
        description="device: call a service on an entity; announce: speak on the speaker; "
                    "scene: run a saved scene by name; delay: wait")
    entity_id: Optional[str] = Field(None, description="device: entity to control")
    service: Optional[str] = Field(None, description="device: turn_on, turn_off, toggle, set_temperature, ...")
    data: Optional[dict[str, Any]] = Field(None, description="device: service data, e.g. {\"temperature\": 26}")
    message: Optional[str] = Field(None, description="announce: what to say, in spoken Chinese")
    urgent: bool = Field(False, description="announce: speak even in quiet hours; only for leak/smoke/gas alarms")
    scene: Optional[str] = Field(None, description="scene: name of a saved scene")
    seconds: Optional[int] = Field(None, description="delay: seconds, 1-3600")


INSTRUCTIONS = (
    "Scenes (run when the user says their phrase) and linkages (run by Home Assistant when "
    "something happens). Read the home-rules skill first. Always confirm with the user before "
    "saving or deleting: home_rule_save and home_rule_delete only check, home_rule_confirm does "
    "it after the user agrees."
)
server = MCPServer("home_rules", instructions=INSTRUCTIONS)


def _ha():
    return HomeAssistant()


def _scenes(items):
    return {i["name"]: i["id"] for i in items if i["kind"] == "scene"}


def _sync_scene_index(ha):
    """Write the saved scene phrases into SOUL.md (see scene_index)."""
    scenes = []
    for item in rules.owned(ha.states()):
        if item["kind"] != "scene":
            continue
        try:
            description = ha.get_config("script", item["id"]).get("description", "")
        except HAError:
            description = ""
        scenes.append((item["name"], str(description).removeprefix(rules.CREATED_BY)))
    try:
        return scene_index.sync(SOUL_PATH, scenes)
    except OSError as e:
        return f"failed: {e}"


@server.tool()
def home_rule_save(
    kind: Literal["scene", "rule"],
    name: str,
    actions: list[Action],
    trigger: Optional[Trigger] = None,
    conditions: Optional[list[Condition]] = None,
    summary: str = "",
    once: bool = False,
) -> dict[str, Any]:
    """Save a scene (kind=scene, run by voice, no trigger) or a linkage (kind=rule, needs a trigger).

    For scenes and lasting linkages this only checks and returns needs_confirmation with
    a summary to read back to the user. After the user agrees, call home_rule_confirm
    (no arguments): it saves what was checked, exactly as read back. A request that needs several (有人开灯 + 没人十分钟关灯) is
    checked one call per item, read back together and confirmed once.
    One-shot linkages (once=true, "just the next time": 这次洗完提醒我) save at once and
    switch themselves off after running. Saving with an existing name replaces it.
    already_saved: the same thing is saved under `name` already; nothing new to save.
    ok=false with problems: fix them or ask the user; nothing is saved.
    summary: one Chinese sentence describing it, used when reading back and listing.
    """
    dump = lambda m: m.model_dump(by_alias=True, exclude_none=True)  # noqa: E731
    args = {"actions": [dump(a) for a in actions], "trigger": dump(trigger) if trigger else None,
            "conditions": [dump(c) for c in conditions or []], "summary": summary, "once": once}
    return _save(kind, name, args, confirmed=False)


def _save(kind, name, args, confirmed):
    ha = _ha()
    try:
        states, services = ha.states(), ha.services()
        items = rules.owned(states)
        config, problems = rules.build(
            kind, name, args["actions"], states, services, trigger=args["trigger"],
            conditions=args["conditions"], summary=args["summary"], scenes=_scenes(items), once=args["once"])
        if problems:
            return {"ok": False, "problems": problems}
        existing = rules.find(items, name, kind)
        exact = [i for i in existing if i["name"] == name.strip()]
        # The agent does not see earlier tool results (xiaozhi forwards text only),
        # so after a retry it may check or save again what is saved under another name.
        twin = None if exact else _saved_twin(ha, items, kind, config)
        if twin:
            PENDING.record(kind, twin["name"], args, saved=True)
            return {"ok": True, "already_saved": True, "kind": kind, "name": twin["name"],
                    "summary": config["description"].removeprefix(rules.CREATED_BY),
                    "next": f"Nothing new: this is already saved as “{twin['name']}”. Tell the user so; "
                            "do not save it again under another name."}
        if not confirmed and not (kind == "rule" and args["once"]):
            if not PENDING.record(kind, name, args):
                return {"ok": False, "problems": ["现在没法记下待确认的内容，稍后再试"]}
            return {"ok": False, "needs_confirmation": True,
                    "summary": config["description"].removeprefix(rules.CREATED_BY),
                    "devices": rules.readback(args["actions"], states, args["trigger"]),
                    "replaces_existing": bool(exact),
                    "next": "Nothing saved yet. Read it back to the user in one sentence, naming the devices "
                            "exactly as `devices` names them (those are the devices that will really be "
                            "switched), and ask whether to save; if they agree, call home_rule_confirm. "
                            "If the request needs more items, check each of them before reading back."}
        object_id = exact[0]["id"] if exact else rules.new_id(kind)
        ha.save_config("script" if kind == "scene" else "automation", object_id, config)
        PENDING.record(kind, name, args, saved=True)
        if kind == "scene":
            _sync_scene_index(ha)
        return {"ok": True, "kind": kind, "name": name.strip(), "id": object_id,
                "replaced": bool(exact), "summary": config["description"]}
    except HAError as e:
        return {"ok": False, "problems": [f"Home Assistant 出错：{e}"]}


def _saved_twin(ha, items, kind, config):
    """A saved scene or linkage that does exactly what config does, under another name.

    One being deleted does not count ("删掉旧的，换个名字再建"); Home Assistant may
    still list it for a moment after the delete.
    """
    config_kind = "script" if kind == "scene" else "automation"
    deleting = PENDING.deleting()
    for item in (i for i in items if i["kind"] == kind and i["id"] not in deleting):
        try:
            if rules.same_behaviour(kind, ha.get_config(config_kind, item["id"]), config):
                return item
        except HAError:
            pass
    return None


@server.tool()
def home_rule_confirm(names: Optional[list[str]] = None) -> dict[str, Any]:
    """Do what home_rule_save or home_rule_delete checked and you read back, once the user agrees
    ("好", "保存吧", "删吧").

    Without names it does everything checked in this exchange and not done yet,
    exactly as checked; names (as given to home_rule_save / home_rule_delete) picks some of them.
    `saved` and `deleted` are what happened now: tell the user only those. Anything you
    read back that is in neither was NOT done; check it first.
    """
    to_do, already = PENDING.batch(names)
    if not to_do:
        if already:
            return {"ok": True, "saved": [], "deleted": [], **_already(already)}
        return {"ok": False, "problems": ["没有等待确认的保存或删除：先用 home_rule_save 或 home_rule_delete 检查，"
                                          "复述给用户，用户同意后再确认。"]}
    # Deletions first: "删掉旧的，换成……" must not find the old one as a twin.
    deleted, problems = _delete([i for i in to_do if pending.op_of(i) == "delete"])
    saved, twins = [], []
    for item in (i for i in to_do if pending.op_of(i) == "save"):
        result = _save(item["kind"], item["name"], item["args"], confirmed=True)
        if result.get("already_saved"):
            twins.append({"kind": item["kind"], "name": result["name"], "summary": result["summary"]})
        elif result.get("ok"):
            saved.append(_described(item))
        else:
            problems += [f"{item['name']}：{p}" for p in result.get("problems", [])]
    result = {"ok": not problems, "saved": saved, "deleted": deleted}
    if twins:
        result["already_saved"] = twins
    return {**result, "problems": problems} if problems else result


def _delete(items):
    """Delete the checked items that are still there: (deleted, problems)."""
    if not items:
        return [], []
    try:
        ha = _ha()
        there = {i["id"] for i in rules.owned(ha.states())}
        deleted = []
        for item in items:
            if item["args"].get("id") in there:
                ha.delete_config("script" if item["kind"] == "scene" else "automation", item["args"]["id"])
            PENDING.record(item["kind"], item["name"], item["args"], saved=True, op="delete")
            deleted.append(_described(item))
        if any(item["kind"] == "scene" for item in items):
            _sync_scene_index(ha)
        return deleted, []
    except HAError as e:
        return [], [f"Home Assistant 出错：{e}"]


def _already(items):
    """What an earlier confirm did, by op: {"already_saved": [...], "already_deleted": [...]}."""
    result = {}
    for item in items:
        key = "already_deleted" if pending.op_of(item) == "delete" else "already_saved"
        result.setdefault(key, []).append(_described(item))
    return result


def _described(item):
    return {"kind": item["kind"], "name": item["name"], "summary": item["args"].get("summary", "")}


@server.tool()
def home_rules_list() -> dict[str, Any]:
    """List the scenes and linkages created by voice, with their summaries."""
    ha = _ha()
    try:
        items = []
        for item in rules.owned(ha.states()):
            kind = "script" if item["kind"] == "scene" else "automation"
            try:
                description = ha.get_config(kind, item["id"]).get("description", "")
            except HAError:
                description = ""
            if rules.is_spent(item, description):
                ha.delete_config(kind, item["id"])  # a one-shot linkage that already ran
                continue
            item["summary"] = str(description).removeprefix(rules.CREATED_BY)
            items.append(item)
        _sync_scene_index(ha)
        return {"scenes": [i for i in items if i["kind"] == "scene"],
                "rules": [i for i in items if i["kind"] == "rule"]}
    except HAError as e:
        return {"ok": False, "problems": [f"Home Assistant 出错：{e}"]}


def _one(name, kind):
    items = rules.owned(_ha().states())
    matches = rules.find(items, name, kind)
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        known = "、".join(i["name"] for i in items) or "（没有）"
        return None, f"没有找到“{name}”，已有：{known}"
    return None, "有多个匹配：" + "、".join(i["name"] for i in matches) + "，请说具体是哪个"


@server.tool()
def home_rule_delete(
    name: str = "",
    kind: Optional[Literal["scene", "rule"]] = None,
    names: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Check which voice-created scenes or linkages a deletion removes; nothing is deleted yet.

    Returns needs_confirmation and to_delete: ask the user whether to delete exactly
    those, by name. After they agree, call home_rule_confirm (no arguments); only
    what is in its `deleted` is gone. Several at once go in names, in this one call:
    a voice turn has only a few tool calls.
    """
    wanted = [n for n in [name, *(names or [])] if n and n.strip()]
    if not wanted:
        return {"ok": False, "problems": ["要说删除哪一个"]}
    try:
        ha = _ha()
        items = rules.owned(ha.states())
        found, missing, problems = [], [], []
        for each in wanted:
            matches = rules.find(items, each, kind)
            if len(matches) > 1:
                problems.append(f"“{each}”有多个匹配：" + "、".join(i["name"] for i in matches) + "，请说具体是哪个")
            elif not matches:
                missing.append(each)
            elif matches[0] not in found:
                found.append(matches[0])
        if missing:
            left = "、".join(i["name"] for i in items) or "（没有）"
            problems.append(f"没有找到“{'、'.join(missing)}”，现在有：{left}")
        to_delete = []
        for item in found:
            config_kind = "script" if item["kind"] == "scene" else "automation"
            try:
                description = ha.get_config(config_kind, item["id"]).get("description", "")
            except HAError:
                description = ""
            args = {"id": item["id"], "summary": str(description).removeprefix(rules.CREATED_BY)}
            if not PENDING.record(item["kind"], item["name"], args, op="delete"):
                return {"ok": False, "problems": ["现在没法记下待确认的内容，稍后再试"]}
            to_delete.append(_described({**item, "args": args}))
        if not to_delete:
            return {"ok": False, "problems": problems}
        result = {"ok": False, "needs_confirmation": True, "to_delete": to_delete,
                  "next": "Nothing deleted yet. Ask the user whether to delete exactly these, naming them; "
                          "if they agree, call home_rule_confirm."}
        return {**result, "problems": problems} if problems else result
    except HAError as e:
        return {"ok": False, "problems": [f"Home Assistant 出错：{e}"]}


@server.tool()
def home_rule_run(name: str) -> dict[str, Any]:
    """Run a scene now (when the user says its phrase), or test a linkage's actions now.

    For a scene, waits until its devices have switched and reports what really
    happened: `say` is the sentence to tell the user; devices in
    not_responding did not change, so never tell the user they did.
    """
    try:
        item, problem = _one(name, None)
        if problem:
            return {"ok": False, "problems": [problem]}
        ha = _ha()
        if item["kind"] == "scene":
            result = scene_run.run(ha, item["entity_id"])
            if result["error"]:
                return {"ok": False, "problems": [f"Home Assistant 出错：{result['error']}"]}
            return {"ok": True, "ran": item["name"], "kind": "scene",
                    "confirmed": [device + verb for device, verb in result["done"]],
                    "not_responding": result["failed"],
                    "not_checked": result["unchecked"],
                    "continues_later": result["later"],
                    "say": scene_run.reply(item["name"], result)}
        ha.call("automation", "trigger", {"entity_id": item["entity_id"], "skip_condition": True})
        return {"ok": True, "ran": item["name"], "kind": item["kind"]}
    except HAError as e:
        return {"ok": False, "problems": [f"Home Assistant 出错：{e}"]}


def main():
    try:
        ha = _ha()
        status = announce.ensure(ha)
        scenes = _sync_scene_index(ha)
    except Exception as e:  # Hermes must still get the tools if HA is briefly down.
        status = scenes = f"failed: {e}"
    print(f"home_rules: announce script {status}; scene index {scenes}", file=sys.stderr)
    if "--install" in sys.argv:
        return
    server.run("stdio")


if __name__ == "__main__":
    main()
