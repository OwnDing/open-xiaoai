"""Local fixes for the Xiaomi Home integration (applied after install/upgrade).

    docker exec homeassistant python3 /opt/xiaoqi-scripts/patch_xiaomi_home.py
    docker restart homeassistant

1. miot_client.set_prop_async: when the cloud reports a device offline it did
   `create_task(await refresh(...))`, awaiting the coroutine and handing its
   `None` result to create_task. On Python 3.14 that raises TypeError, so HA
   answered 500 instead of the integration's "device offline" error.

Each fix is skipped when already applied or when upstream changed the code.
"""

from pathlib import Path

CLIENT = Path("/config/custom_components/xiaomi_home/miot/miot_client.py")

FIXES = [
    (
        CLIENT,
        "self._main_loop.create_task(\n"
        "                        await self.__refresh_cloud_device_with_dids_async(",
        "self._main_loop.create_task(\n"
        "                        self.__refresh_cloud_device_with_dids_async(",
    ),
]


def main():
    for path, old, new in FIXES:
        source = path.read_text(encoding="utf-8")
        count = source.count(old)
        if count:
            path.write_text(source.replace(old, new), encoding="utf-8")
            print(f"patched {path.name}: {count} occurrence(s)")
        elif new in source:
            print(f"already patched {path.name}")
        else:
            print(f"WARNING: pattern not found in {path.name}; upstream code changed")


if __name__ == "__main__":
    main()
