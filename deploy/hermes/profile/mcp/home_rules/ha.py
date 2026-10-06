"""Minimal Home Assistant REST client (standard library only)."""

import json
import os
import urllib.error
import urllib.request


class HAError(Exception):
    pass


class HomeAssistant:
    def __init__(self, url=None, token=None, timeout=20):
        self.url = (url or os.environ["HASS_URL"]).rstrip("/")
        self.token = token or os.environ["HASS_TOKEN"]
        self.timeout = timeout

    def request(self, method, path, body=None):
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
        return json.loads(raw) if raw else None

    def states(self):
        return self.request("GET", "/api/states")

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
