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

from . import announce, rules, scene_index
from .ha import HAError, HomeAssistant

SOUL_PATH = os.environ.get("SOUL_PATH", "/opt/data/SOUL.md")


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
    "saving or deleting."
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
    confirmed: bool = False,
) -> dict[str, Any]:
    """Save a scene (kind=scene, run by voice, no trigger) or a linkage (kind=rule, needs a trigger).

    Scenes and lasting linkages take two calls: the first (confirmed=false) only checks
    and returns needs_confirmation with a summary to read back to the user; after the
    user agrees, call again with the same arguments and confirmed=true to save.
    One-shot linkages (once=true, "just the next time": 这次洗完提醒我) save at once and
    switch themselves off after running. Saving with an existing name replaces it.
    ok=false with problems: fix them or ask the user; nothing is saved.
    summary: one Chinese sentence describing it, used when reading back and listing.
    """
    ha = _ha()
    try:
        states, services = ha.states(), ha.services()
        items = rules.owned(states)
        dump = lambda m: m.model_dump(by_alias=True, exclude_none=True)  # noqa: E731
        config, problems = rules.build(
            kind, name, [dump(a) for a in actions], states, services,
            trigger=dump(trigger) if trigger else None,
            conditions=[dump(c) for c in conditions or []],
            summary=summary, scenes=_scenes(items), once=once)
        if problems:
            return {"ok": False, "problems": problems}
        existing = rules.find(items, name, kind)
        exact = [i for i in existing if i["name"] == name.strip()]
        if not confirmed and not (kind == "rule" and once):
            return {"ok": False, "needs_confirmation": True,
                    "summary": config["description"].removeprefix(rules.CREATED_BY),
                    "replaces_existing": bool(exact),
                    "next": "Nothing saved yet. Read the summary back to the user in one sentence and ask "
                            "whether to save; if they agree, call again with the same arguments and confirmed=true."}
        if not exact:
            # The agent does not see earlier tool results (xiaozhi forwards text only),
            # so after a retry it may save what is already saved under another name.
            config_kind = "script" if kind == "scene" else "automation"
            for item in (i for i in items if i["kind"] == kind):
                try:
                    if rules.same_behaviour(kind, ha.get_config(config_kind, item["id"]), config):
                        return {"ok": True, "already_saved": True, "kind": kind, "name": item["name"],
                                "summary": config["description"]}
                except HAError:
                    pass
        object_id = exact[0]["id"] if exact else rules.new_id(kind)
        ha.save_config("script" if kind == "scene" else "automation", object_id, config)
        if kind == "scene":
            _sync_scene_index(ha)
        return {"ok": True, "kind": kind, "name": name.strip(), "id": object_id,
                "replaced": bool(exact), "summary": config["description"]}
    except HAError as e:
        return {"ok": False, "problems": [f"Home Assistant 出错：{e}"]}


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
def home_rule_delete(name: str, kind: Optional[Literal["scene", "rule"]] = None) -> dict[str, Any]:
    """Delete a voice-created scene or linkage by name (confirm with the user first)."""
    try:
        item, problem = _one(name, kind)
        if problem:
            return {"ok": False, "problems": [problem]}
        ha = _ha()
        ha.delete_config("script" if item["kind"] == "scene" else "automation", item["id"])
        if item["kind"] == "scene":
            _sync_scene_index(ha)
        return {"ok": True, "deleted": item["name"], "kind": item["kind"]}
    except HAError as e:
        return {"ok": False, "problems": [f"Home Assistant 出错：{e}"]}


@server.tool()
def home_rule_run(name: str) -> dict[str, Any]:
    """Run a scene now (when the user says its phrase), or test a linkage's actions now."""
    try:
        item, problem = _one(name, None)
        if problem:
            return {"ok": False, "problems": [problem]}
        ha = _ha()
        if item["kind"] == "scene":
            ha.call("script", item["id"])
        else:
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
