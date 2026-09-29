"""Onboard the demo Home Assistant and store a long-lived token for Hermes.

Creates the owner user, exchanges the onboarding auth code for an access
token, mints a long-lived access token over the WebSocket API, and writes
HASS_URL/HASS_TOKEN into the Hermes .env file. The token is never printed.

    docker run --rm --network xiaozhi-server_default \
        -v <deploy/hermes>:/hermes --entrypoint /app/.venv/bin/python \
        local/open-xiaoai-xiaozhi:smooth-audio /hermes/demo-ha/onboard.py
"""

import asyncio
import json
import os
import secrets
import time
from pathlib import Path

import requests
import websockets

HA_URL = os.environ.get("HA_URL", "http://homeassistant:8123")
ENV_PATH = Path(os.environ.get("ENV_PATH", "/hermes/.env"))
CLIENT_ID = HA_URL + "/"


def wait_ready():
    for _ in range(120):
        try:
            if requests.get(f"{HA_URL}/api/onboarding", timeout=3).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise SystemExit("Home Assistant did not become ready")


def onboard_owner():
    steps = requests.get(f"{HA_URL}/api/onboarding", timeout=10).json()
    user_step = next(step for step in steps if step["step"] == "user")
    if user_step["done"]:
        raise SystemExit("Owner already exists; delete the ha-demo-data volume to re-onboard")
    password = secrets.token_urlsafe(24)
    resp = requests.post(
        f"{HA_URL}/api/onboarding/users",
        json={
            "client_id": CLIENT_ID,
            "name": "Xiaoqi",
            "username": "xiaoqi",
            "password": password,
            "language": "zh-Hans",
        },
        timeout=30,
    )
    resp.raise_for_status()
    auth_code = resp.json()["auth_code"]
    token = requests.post(
        f"{HA_URL}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": CLIENT_ID,
        },
        timeout=30,
    )
    token.raise_for_status()
    access_token = token.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    for step, body in (
        ("core_config", {}),
        ("analytics", {}),
        ("integration", {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID}),
    ):
        requests.post(f"{HA_URL}/api/onboarding/{step}", json=body, headers=headers, timeout=30)
    return access_token


async def mint_long_lived(access_token):
    ws_url = HA_URL.replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(ws_url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": access_token}))
        if json.loads(await ws.recv())["type"] != "auth_ok":
            raise SystemExit("WebSocket auth failed")
        await ws.send(
            json.dumps(
                {
                    "id": 1,
                    "type": "auth/long_lived_access_token",
                    "client_name": "hermes-xiaoqi-home",
                    "lifespan": 3650,
                }
            )
        )
        reply = json.loads(await ws.recv())
        if not reply.get("success"):
            raise SystemExit(f"Could not mint token: {reply.get('error')}")
        return reply["result"]


def write_env(token):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    values = {"HASS_URL": HA_URL, "HASS_TOKEN": token}
    output = []
    for line in lines:
        key = line.split("=", 1)[0]
        if key in values:
            output.append(f"{key}={values.pop(key)}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in values.items())
    ENV_PATH.write_text("\n".join(output) + "\n", encoding="utf-8")


def main():
    wait_ready()
    access_token = onboard_owner()
    token = asyncio.run(mint_long_lived(access_token))
    write_env(token)
    states = requests.get(
        f"{HA_URL}/api/states",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    ).json()
    print(f"Stored HASS_URL/HASS_TOKEN in {ENV_PATH}")
    for state in states:
        if state["entity_id"].split(".")[0] in {"light", "climate", "sensor", "binary_sensor"}:
            print(state["entity_id"], state["state"], state["attributes"].get("friendly_name"))


if __name__ == "__main__":
    main()
