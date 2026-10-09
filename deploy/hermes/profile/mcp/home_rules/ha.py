"""Minimal Home Assistant REST client (standard library only)."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class HAError(Exception):
    pass


class HomeAssistant:
    def __init__(self, url=None, token=None, timeout=20):
        self.url = (url or os.environ["HASS_URL"]).rstrip("/")
        self.token = token or os.environ["HASS_TOKEN"]
        self.timeout = timeout

    def request(self, method, path, body=None, text=False):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(
            self.url + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            raise HAError(f"{method} {path}: HTTP {e.code} {detail}") from None
        if text:
            return raw.decode("utf-8")
        return json.loads(raw) if raw else None

    def states(self):
        return self.request("GET", "/api/states")

    def state(self, entity_id):
        return self.request("GET", f"/api/states/{entity_id}")

    def config(self):
        return self.request("GET", "/api/config")

    # Recorder history and logbook (home_history); start/end are aware datetimes.
    def history(self, entity_id, start, end):
        query = urllib.parse.urlencode({"filter_entity_id": entity_id, "end_time": end.isoformat()})
        rows = self.request("GET", f"/api/history/period/{urllib.parse.quote(start.isoformat())}"
                                   f"?{query}&minimal_response&no_attributes")
        return rows[0] if rows else []

    def device_entities(self, entity_id):
        """Every entity of the device entity_id belongs to ([] if none); entity_id must be validated."""
        template = "{{ device_entities(device_id('%s')) | list | tojson }}" % entity_id
        return json.loads(self.request("POST", "/api/template", {"template": template}, text=True) or "[]")

    def logbook(self, entity_id, start, end):
        query = urllib.parse.urlencode({"entity": entity_id, "end_time": end.isoformat()})
        return self.request("GET", f"/api/logbook/{urllib.parse.quote(start.isoformat())}?{query}") or []

    def services(self):
        return {s["domain"]: s["services"] for s in self.request("GET", "/api/services")}

    # kind is "automation" or "script"; HA reloads them after a write.
    def get_config(self, kind, object_id):
        return self.request("GET", f"/api/config/{kind}/config/{object_id}")

    def save_config(self, kind, object_id, config):
        return self.request("POST", f"/api/config/{kind}/config/{object_id}", config)

    def delete_config(self, kind, object_id):
        return self.request("DELETE", f"/api/config/{kind}/config/{object_id}")

    def call(self, domain, service, data=None):
        return self.request("POST", f"/api/services/{domain}/{service}", data or {})
