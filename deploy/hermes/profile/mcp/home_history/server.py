"""MCP server "home_history": what devices did in the past, from Home Assistant's recorder.

    python -m home_history.server    # stdio, started by Hermes (mcp_servers)

Read only. Needs HASS_URL and HASS_TOKEN; reuses the home_rules HA client.
Hermes' own Home Assistant tools only see the present state, so without this
the agent answered "鱼缸灯今天亮了多久" with "插座没有记录".
"""

import sys
from datetime import datetime
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer

from home_rules.ha import HAError, HomeAssistant

from . import history

MAX_ENTITIES = 10

INSTRUCTIONS = (
    "Past behaviour of home devices from Home Assistant's history: how long something was on, "
    "when and by whom it was switched, how often, sensor min/max/average, energy used."
)
server = MCPServer("home_history", instructions=INSTRUCTIONS)
_zone = None


def _tz(ha):
    global _zone
    if _zone is None:
        _zone = ZoneInfo(ha.config().get("time_zone") or "Asia/Shanghai")
    return _zone


def _power(ha, entity_id, lo, hi, now, tz):
    """Power use of the device a switch belongs to ("鱼缸灯今天用了多少电" names the plug's switch).

    The device table only lists switches, and the model guessed a wattage when
    it had none, so the plug's power sensor is found through the device here.
    """
    try:
        siblings = ha.device_entities(entity_id)
    except (HAError, ValueError):
        return None
    for sibling in siblings:
        if not (sibling.startswith("sensor.") and history.ENTITY_ID.match(sibling)):
            continue
        try:
            current = ha.state(sibling)
        except HAError:
            continue
        if current.get("attributes", {}).get("unit_of_measurement") not in history.POWER_UNITS:
            continue
        rows = ha.history(sibling, lo, hi)
        power = history.power_of(history.summarize(sibling, current, rows, [], lo, hi, now, tz))
        if power:
            return power
    return None


@server.tool()
def device_history(
    entity_ids: list[str],
    period: Literal["today", "yesterday", "last_24h", "this_week", "last_7_days",
                    "this_month", "last_30_days"] = "today",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict[str, Any]:
    """What devices did in the past, worked out from Home Assistant's history.

    Use for questions about the past: 今天鱼缸灯亮了多久, 客厅灯几点开的/谁关的, 空调昨天开了几次,
    这几天平均每天开多久, 昨晚卧室最低温度, 今天鱼缸用了多少电.
    Not for the current state (use ha_get_state).

    entity_ids: 1-10 entity ids from the device table.
    period: today (midnight to now), yesterday, last_24h, this_week (since Monday), last_7_days,
    this_month, last_30_days. start/end override its edges for other spans, e.g. 昨晚 =
    start "yesterday 18:00", end "today 08:00"; also "HH:MM" (today) or "YYYY-MM-DD HH:MM".

    Switches/lights/fans/etc.: on_total (already added up), times_switched_on, on_periods with
    on/off times and on_by/off_by (小七 = done through Home Assistant, i.e. you), per_day and
    average_per_full_day for spans longer than a day, and power (max watts and
    estimated_energy_kwh) when the device measures it: for 用了多少电 pass the switch itself.
    Sensors: min/max with times and average; energy/water meters: used. Other devices:
    time_in_state and changes. records_from means
    there is no history before that time; no_records means nothing was recorded in the span.
    Read the numbers out as they are; do not add them up yourself.
    """
    try:
        ha = HomeAssistant()
        tz = _tz(ha)
        now = datetime.now(tz)
        try:
            lo, hi = history.window(now, period, start, end)
        except ValueError as e:
            return {"ok": False, "problems": [str(e)]}
        results, problems = [], []
        for entity_id in [e.strip() for e in entity_ids][:MAX_ENTITIES]:
            if not history.ENTITY_ID.match(entity_id):
                problems.append(f"实体 ID 格式不对：{entity_id}")
                continue
            try:
                current = ha.state(entity_id)
            except HAError as e:
                problems.append(f"没有找到 {entity_id}，先用 ha_list_entities 查实体 ID" if "404" in str(e) else str(e))
                continue
            rows = ha.history(entity_id, lo, hi)
            logbook = []
            switch = entity_id.split(".", 1)[0] not in history.EVENTS and any(
                history.is_on(entity_id.split(".", 1)[0], str(r.get("state"))) is not None for r in rows)
            if switch:
                logbook = ha.logbook(entity_id, lo, hi)
            summary = history.summarize(entity_id, current, rows, logbook, lo, hi, now, tz)
            if switch:
                power = _power(ha, entity_id, lo, hi, now, tz)
                if power:
                    summary["power"] = power
            results.append(summary)
        out = {"ok": bool(results), "range": history.fmt_range(lo, hi, now), "devices": results}
        if problems:
            out["problems"] = problems
        return out
    except HAError as e:
        return {"ok": False, "problems": [f"Home Assistant 出错：{e}"]}


def main():
    print("home_history: ready", file=sys.stderr)
    server.run("stdio")


if __name__ == "__main__":
    main()
