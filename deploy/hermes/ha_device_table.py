"""Generate the Home Assistant device table in profile/SOUL.md.

Hermes controls a device in one tool round when it already knows the entity
id, so SOUL.md carries a compact table of the controllable entities, grouped
by area. Entities follow Home Assistant's Settings > Voice assistants > Expose
switches: exposed ones are listed (feature switches of a light, fan or speaker
excepted), unexposed ones are left out. Entities Home Assistant has not
decided on yet fall back to the domain rules below.

Re-run this after adding or renaming devices, or changing what is exposed:

    docker run --rm --network xiaozhi-server_default --env-file .env \
        -v ${PWD}:/hermes --entrypoint /app/.venv/bin/python \
        local/open-xiaoai-xiaozhi:smooth-audio /hermes/ha_device_table.py
    docker compose run --rm --entrypoint sh hermes /seed/profile/install.sh
"""

import asyncio
import json
import os
import re
from collections import defaultdict
from pathlib import Path

import websockets

SOUL_PATH = Path(os.environ.get("SOUL_PATH", "/hermes/profile/SOUL.md"))
START = "<!-- devices:start -->"
END = "<!-- devices:end -->"

# Domains a voice user controls or asks about. Config/diagnostic entities
# (indicator lights, firmware switches, signal strength...) are skipped.
CONTROL_DOMAINS = {
    "light", "switch", "climate", "fan", "cover", "humidifier",
    "vacuum", "water_heater", "media_player", "lock", "scene",
}
SENSOR_CLASSES = {
    "sensor": {"temperature", "humidity", "pm25", "carbon_dioxide", "illuminance"},
    "binary_sensor": {"door", "window", "motion", "occupancy", "moisture"},
}
# Appliances (fridge, washer...) bring dozens of entities; their status
# sensors and set-points are listed only once exposed to voice assistants.
EXPOSABLE_DOMAINS = {"sensor", "binary_sensor", "select", "number", "button"}
MAX_LINES = 80


async def call(ws, message_id, payload):
    await ws.send(json.dumps({"id": message_id, **payload}))
    while True:
        reply = json.loads(await ws.recv())
        if reply.get("id") == message_id:
            if not reply.get("success"):
                raise SystemExit(f"{payload['type']} failed: {reply.get('error')}")
            return reply["result"]


async def fetch():
    url = os.environ["HASS_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(url, max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": os.environ["HASS_TOKEN"]}))
        if json.loads(await ws.recv()).get("type") != "auth_ok":
            raise SystemExit("Home Assistant rejected HASS_TOKEN")
        areas = await call(ws, 1, {"type": "config/area_registry/list"})
        devices = await call(ws, 2, {"type": "config/device_registry/list"})
        entities = await call(ws, 3, {"type": "config/entity_registry/list"})
        states = await call(ws, 4, {"type": "get_states"})
    return areas, devices, entities, states


def clean_name(name):
    """Collapse Xiaomi Home's "设备名  实体名" and drop a redundant trailing kind."""
    parts = name.replace("*", " ").split()
    if len(parts) > 1 and parts[0].endswith(parts[-1]):
        parts = parts[:-1]
    deduped = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return " ".join(deduped)


def exposed(entry):
    """True/False as set under Voice assistants > Expose; None if not decided yet."""
    return ((entry.get("options") or {}).get("conversation") or {}).get("should_expose")


def build_lines(areas, devices, entities, states):
    area_names = {area["area_id"]: area["name"] for area in areas}
    device_area = {device["id"]: device.get("area_id") for device in devices}
    registry = {entity["entity_id"]: entity for entity in entities}

    # A device with a primary entity (light, fan, speaker...) also exposes
    # feature switches (sleep mode, child lock, mic mute...). Only list those
    # switches for devices whose switch *is* the device, e.g. a smart plug.
    # Config entities don't count: a plug's indicator LED is a "light".
    primary_devices = {
        entity.get("device_id")
        for entity in entities
        if entity["entity_id"].split(".", 1)[0] in CONTROL_DOMAINS - {"switch", "scene"}
        and not (entity.get("entity_category") or entity.get("disabled_by") or entity.get("hidden_by"))
    }

    grouped = defaultdict(list)
    for state in states:
        entity_id = state["entity_id"]
        domain = entity_id.split(".", 1)[0]
        attributes = state.get("attributes", {})
        entry = registry.get(entity_id, {})
        if entry.get("entity_category") or entry.get("disabled_by") or entry.get("hidden_by"):
            continue
        # Xiaomi Home marks vendor-specific properties with "*" (a plug's
        # LED do-not-disturb, charge protection, timers...). Home Assistant
        # exposes new switches by default, so leave these out of the table;
        # Hermes can still find them with ha_list_entities.
        if (entry.get("original_name") or "").lstrip().startswith("*"):
            continue
        if exposed(entry) is None:
            listed = (
                domain in CONTROL_DOMAINS
                or attributes.get("device_class") in SENSOR_CLASSES.get(domain, ())
            )
        else:
            listed = exposed(entry) and domain in CONTROL_DOMAINS | EXPOSABLE_DOMAINS
        if not listed:
            continue
        if domain == "switch" and entry.get("device_id") in primary_devices:
            continue
        area_id = entry.get("area_id") or device_area.get(entry.get("device_id"))
        area = area_names.get(area_id, "未分配房间")
        grouped[area].append(f"{clean_name(attributes.get('friendly_name') or entity_id)} {entity_id}")

    lines = []
    for area in sorted(grouped):
        lines.append(f"- {area}：" + "；".join(sorted(grouped[area])))
    return lines


def write_soul(lines, total):
    soul = SOUL_PATH.read_text(encoding="utf-8")
    if START not in soul or END not in soul:
        raise SystemExit(f"{SOUL_PATH} has no {START} ... {END} block")
    if not lines:
        body = "（尚未从 Home Assistant 同步到设备，控制前先用 `ha_list_entities` 查找。）"
    else:
        body = "\n".join(lines[:MAX_LINES])
        if len(lines) > MAX_LINES:
            body += f"\n- ……其余 {len(lines) - MAX_LINES} 个房间未列出，用 `ha_list_entities` 查找。"
    block = f"{START}\n{body}\n{END}"
    soul = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, soul, flags=re.S)
    SOUL_PATH.write_text(soul, encoding="utf-8")
    print(f"Wrote {min(len(lines), MAX_LINES)} area lines ({total} entities) into {SOUL_PATH}")


def main():
    areas, devices, entities, states = asyncio.run(fetch())
    lines = build_lines(areas, devices, entities, states)
    total = sum(line.count("；") + 1 for line in lines)
    for line in lines:
        print(line)
    write_soul(lines, total)


if __name__ == "__main__":
    main()
