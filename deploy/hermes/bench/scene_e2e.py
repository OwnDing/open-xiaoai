"""End-to-end check that a saved scene phrase really switches its devices.

Replays the 2026-10-11 conversation that went wrong ("我回来了" answered with
"客厅灯和餐厅灯都开了" while nothing was switched) through xiaozhi-esp32-server
as text on one connection, so the server keeps the dialogue history. Before
each phrase the scene's devices are switched back with Home Assistant; after
the reply their states are read. A turn fails when the devices did not reach
the scene's states, or when the reply says something was switched that was not.

Run it inside a xiaozhi-esp32-server container whose provider has Home
Assistant access (ha_url/ha_token in the HermesAgentLLM entry):

    docker cp scene_e2e.py <container>:/tmp/ && docker exec <container> python /tmp/scene_e2e.py

It switches the scene's real devices (daytime only) and restores them at the end.
"""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid

import websockets
import yaml

APP = "/opt/xiaozhi-esp32-server"
MODULES = APP + "/core/providers/llm/hermes"
# (what the user says, whether the devices must end up switched). The devices
# are switched back before every turn, so each one starts from "not done".
CASES = [
    ("我回来了。", True),
    ("小琪，我回来了。", True),
    ("我回来啦。", True),
    ("我回来了。", True),
    ("我回来了，现在几点了？", True),
    # Switched back behind 小七's back: it must switch them again.
    ("没开呀。", True),
    # Not the exact phrase: the model decides, but must not claim what it did not do.
    ("我已经回到家了。", False),
]


def load(config_path, modules):
    sys.path[:0] = [modules, APP]
    import ha as ha_client  # noqa: E402 (mounted next to hermes.py)
    import hermes  # noqa: E402
    import scene_run  # noqa: E402

    config = yaml.safe_load(open(config_path, encoding="utf-8"))
    llm = config["LLM"][config["selected_module"]["LLM"]]
    return ha_client.HomeAssistant(llm["ha_url"], llm["ha_token"]), scene_run, hermes


def switch_back(ha, checks):
    for entity_id, (accept, _) in checks.items():
        domain = entity_id.split(".", 1)[0]
        service = "turn_on" if accept == {"off"} else "turn_off"
        ha.call(domain, service, {"entity_id": entity_id})
    time.sleep(2)


def states(ha, checks):
    return {entity_id: ha.state(entity_id)["state"] for entity_id in checks}


async def ask(ws, session_id, text):
    await ws.send(json.dumps({"session_id": session_id, "type": "listen", "state": "detect", "text": text}))
    sentences, t0, first = [], time.perf_counter(), None
    while True:
        message = await asyncio.wait_for(ws.recv(), 90)
        if isinstance(message, bytes):
            continue
        data = json.loads(message)
        if data.get("type") == "tts" and data.get("state") == "sentence_start":
            first = first or round(time.perf_counter() - t0, 2)
            sentences.append(data.get("text", ""))
        if data.get("type") == "tts" and data.get("state") == "stop":
            return "".join(sentences), first


async def main(args, ha, scene_run, hermes):
    scenes = scene_run.list_scenes(ha)
    if args.phrase not in scenes:
        raise SystemExit(f"no saved scene “{args.phrase}”; saved: {list(scenes)}")
    checks, _, _ = scene_run.plan(ha, scenes[args.phrase])
    if not checks:
        raise SystemExit("the scene has no device whose state can be checked")
    before = states(ha, checks)
    print(f"scene “{args.phrase}” -> {scenes[args.phrase]}; devices {before}", flush=True)

    headers = {"Authorization": "Bearer bench", "Protocol-Version": "1",
               "Device-Id": args.device_id, "Client-Id": str(uuid.uuid4())}
    failures = 0
    try:
        async with websockets.connect(args.url, additional_headers=headers, max_size=None) as ws:
            await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                      "audio_params": {"format": "opus", "sample_rate": 16000,
                                                       "channels": 1, "frame_duration": 60}}))
            while True:
                message = json.loads(await ws.recv())
                if message.get("type") == "hello":
                    session_id = message.get("session_id", "")
                    break
            for text, must_switch in CASES:
                switch_back(ha, checks)
                reply, first = await ask(ws, session_id, text)
                time.sleep(1)
                now = states(ha, checks)
                switched = all(scene_run.satisfied(accept, now[e]) for e, (accept, _) in checks.items())
                # "开了", or a state such as "开着呢" (the test scene turns things on).
                claimed = hermes.says_done(reply) or bool(re.search(r"(?:开|亮)着|开了|亮了", reply))
                ok = switched if must_switch else (switched or not claimed)
                failures += not ok
                print(f"{'PASS' if ok else 'FAIL'} | {text} | first {first}s | {reply} | "
                      f"switched={switched} claimed={claimed} {now}", flush=True)
                await asyncio.sleep(2)
    finally:
        for entity_id, value in before.items():
            if value in ("on", "off"):
                ha.call(entity_id.split(".", 1)[0], f"turn_{value}", {"entity_id": entity_id})
        print(f"restored {before}", flush=True)
    print(f"{len(CASES) - failures}/{len(CASES)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000/xiaozhi/v1/")
    parser.add_argument("--config", default="/opt/xiaozhi-esp32-server/data/.config.yaml")
    parser.add_argument("--modules", default=MODULES)
    parser.add_argument("--phrase", default="我回来了")
    parser.add_argument("--device-id", default="02:76:74:00:00:fe")
    args = parser.parse_args()
    # xiaozhi's logger loads its config with asyncio.run: import before the loop starts.
    asyncio.run(main(args, *load(args.config, args.modules)))
