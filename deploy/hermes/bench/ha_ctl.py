"""Set/read demo HA state for tests: ha_ctl.py reset | show"""
import os, sys, requests
B = os.environ["HASS_URL"]; H = {"Authorization": "Bearer " + os.environ["HASS_TOKEN"]}
def call(domain, service, **data):
    requests.post(f"{B}/api/services/{domain}/{service}", json=data, headers=H, timeout=20).raise_for_status()
if sys.argv[1] == "reset":
    call("light", "turn_on", entity_id=["light.ke_ting_deng", "light.shu_fang_deng"])
    call("climate", "set_temperature", entity_id="climate.wo_shi_kong_diao", temperature=28)
for s in requests.get(f"{B}/api/states", headers=H, timeout=20).json():
    if s["entity_id"].split(".")[0] in ("light", "climate"):
        print(s["entity_id"], s["state"], s["attributes"].get("temperature", ""), s["last_changed"])
