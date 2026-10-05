"""Pull newly added Mijia devices into Home Assistant (Xiaomi Home "update devices").

Same as Settings > Devices & services > Xiaomi Home > Configure > tick
"Update devices", keeping every other option as it is. Run inside the HA
container with a long-lived token in HASS_TOKEN:

    docker exec --env-file ..\\hermes\\.env homeassistant python3 /opt/xiaoqi-scripts/xiaomi_update_devices.py --check
    docker exec --env-file ..\\hermes\\.env homeassistant python3 /opt/xiaoqi-scripts/xiaomi_update_devices.py

--check stops before saving and only reports how many devices would be added
or removed. Without it the change is saved (the integration reloads, Mijia
devices are unavailable for a few seconds); if devices would be removed it
gives up unless --allow-remove is passed.
"""

import argparse
import json
import os
import sys
import urllib.request

BASE = os.environ.get("HASS_LOCAL_URL", "http://127.0.0.1:8123")


def api(method, path, body=None):
    request = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['HASS_TOKEN'].strip()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read() or b"null")


def update(entry, check, allow_remove):
    flow = "/api/config/config_entries/options/flow"
    step = api("POST", flow, {"handler": entry["entry_id"], "show_advanced_options": False})
    seen = set()

    def abort(message):
        api("DELETE", f"{flow}/{step['flow_id']}")
        print(message)
        return False

    while step.get("type") == "form":
        step_id = step["step_id"]
        if step_id in seen:
            return abort(f"step {step_id} was shown again ({step.get('errors')}); nothing saved")
        seen.add(step_id)
        values = {f["name"]: f.get("default") for f in step.get("data_schema", [])}
        if step_id == "config_options":
            values["update_devices"] = True
        elif step_id == "config_confirm":
            info = step.get("description_placeholders") or {}
            added, removed = int(info.get("devices_add", 0)), int(info.get("devices_remove", 0))
            print(f"devices to add: {added}, to remove: {removed}")
            if check:
                abort("--check: nothing saved")
                return True
            if removed and not allow_remove:
                return abort("devices would be removed; nothing saved (use --allow-remove if intended)")
            values["confirm"] = True
        elif step_id not in ("homes_select", "devices_filter"):
            print(f"note: submitting unexpected step {step_id} with its defaults")
        step = api("POST", f"{flow}/{step['flow_id']}", {k: v for k, v in values.items() if v is not None})
    if step.get("type") == "abort":
        print(f"aborted by Xiaomi Home: {step.get('reason')} {step.get('description_placeholders') or ''}")
        return False
    print("saved; Xiaomi Home is reloading")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report changes without saving")
    parser.add_argument("--allow-remove", action="store_true", help="also save when devices would be removed")
    args = parser.parse_args()
    if "HASS_TOKEN" not in os.environ:
        sys.exit("HASS_TOKEN is not set (docker exec --env-file ..\\hermes\\.env ...)")
    entries = [e for e in api("GET", "/api/config/config_entries/entry") if e["domain"] == "xiaomi_home"]
    if not entries:
        sys.exit("no Xiaomi Home integration")
    ok = True
    for entry in entries:
        print(f"{entry['title']} ({entry['state']})")
        ok = update(entry, args.check, args.allow_remove) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
