"""Toggle one real device through Hermes and time it, then restore it.

    python real_ha_test.py <entity_id> <on-phrase> <off-phrase>

Sends the phrase that flips the entity's current state to Hermes, polls Home
Assistant until the state changes, then sends the opposite phrase to restore.
"""

import json
import os
import sys
import threading
import time

import requests

HASS = os.environ["HASS_URL"].rstrip("/")
HA_HEADERS = {"Authorization": "Bearer " + os.environ["HASS_TOKEN"]}
HERMES = "http://hermes:8642/v1/chat/completions"
HERMES_HEADERS = {"Authorization": "Bearer " + os.environ["API_SERVER_KEY"]}


def state(entity_id):
    return requests.get(f"{HASS}/api/states/{entity_id}", headers=HA_HEADERS, timeout=10).json()["state"]


def ask(entity_id, phrase, before):
    body = {"model": "xiaoqi-home", "stream": True, "messages": [{"role": "user", "content": phrase}]}
    changed = {}
    done = threading.Event()

    def poll():
        while not done.is_set():
            if state(entity_id) != before:
                changed["t"] = time.perf_counter() - t0
                return
            time.sleep(0.1)

    t0 = time.perf_counter()
    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    first_text = None
    text = ""
    with requests.post(HERMES, json=body, headers=HERMES_HEADERS, stream=True, timeout=60) as resp:
        for raw in resp.iter_lines(decode_unicode=True):
            if raw and raw.startswith("data:") and raw[5:].strip() != "[DONE]":
                try:
                    delta = json.loads(raw[5:])["choices"][0]["delta"].get("content") or ""
                except (KeyError, IndexError, json.JSONDecodeError):
                    delta = ""
                if delta.strip() and first_text is None:
                    first_text = time.perf_counter() - t0
                text += delta
    poller.join(timeout=10)
    done.set()
    return {
        "phrase": phrase,
        "before": before,
        "after": state(entity_id),
        "ha_changed_s": round(changed["t"], 2) if "t" in changed else None,
        "first_text_s": round(first_text, 2) if first_text else None,
        "answer": text.strip(),
    }


def main():
    entity_id, on_phrase, off_phrase = sys.argv[1:4]
    before = state(entity_id)
    first, second = (off_phrase, on_phrase) if before == "on" else (on_phrase, off_phrase)
    result = ask(entity_id, first, before)
    print(json.dumps(result, ensure_ascii=False))
    time.sleep(3)
    print(json.dumps(ask(entity_id, second, state(entity_id)), ensure_ascii=False))
    print("restored" if state(entity_id) == before else f"NOT restored: {state(entity_id)} (was {before})")


if __name__ == "__main__":
    main()
