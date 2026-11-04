"""Print CAMS=... for cams.env from HA's generic camera entries (sub-stream URLs).

Run in the homeassistant container; the output holds the camera passwords:
  docker exec -i homeassistant python3 - < cams_from_ha.py > cams.env
Names: NAMES maps the HA entry title to the short camera name used here.
"""

import json
import urllib.parse as up

NAMES = {"192_168_254_200": "keting", "192_168_254_201": "lianlang"}

entries = json.load(open("/config/.storage/core.config_entries"))["data"]["entries"]
parts = []
for c in entries:
    if c["domain"] == "generic" and c["title"] in NAMES:
        o = c["options"]
        cred = up.quote(o["username"], safe="") + ":" + up.quote(o["password"], safe="") + "@"
        url = o["stream_source"].replace("rtsp://", "rtsp://" + cred).replace("Channels/101", "Channels/102")
        parts.append(NAMES[c["title"]] + "=" + url)
print("CAMS=" + ";".join(parts))
