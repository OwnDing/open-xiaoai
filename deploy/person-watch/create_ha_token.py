"""Create a long-lived HA token named person-watch and print it as HA_TOKEN=...

Run inside the homeassistant container with an existing admin token on stdin:
  docker exec hermes printenv HASS_TOKEN | docker exec -i homeassistant python3 /tmp/create_ha_token.py > .env
"""

import asyncio
import sys

import aiohttp


async def main():
    token = sys.stdin.read().strip()
    async with aiohttp.ClientSession() as s, s.ws_connect("http://127.0.0.1:8123/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        msg = await ws.receive_json()
        if msg["type"] != "auth_ok":
            raise SystemExit(f"auth failed: {msg['type']}")
        await ws.send_json({"id": 1, "type": "auth/long_lived_access_token", "client_name": "person-watch", "lifespan": 3650})
        msg = await ws.receive_json()
        if not msg.get("success"):
            raise SystemExit(f"token not created: {msg.get('error')}")
        print("HA_TOKEN=" + msg["result"])


asyncio.run(main())
