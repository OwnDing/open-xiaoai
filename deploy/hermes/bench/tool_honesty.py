"""Does Hermes really call a tool when the chat history shows past "done" replies?

xiaozhi-esp32-server sends the dialogue as plain text, so earlier turns look
like the assistant switched lights without any tool call. This replays that
shape and checks whether the new request triggers `ha_call_service`.

    python tool_honesty.py <entity_id> <device name> <trials>

Alternates off/on so the device ends in its original state (when it was on).
"""

import json
import os
import sys

import requests

HERMES = "http://hermes:8642/v1/chat/completions"
HEADERS = {"Authorization": "Bearer " + os.environ["API_SERVER_KEY"]}


def user(text):
    # xiaozhi wraps ASR output with language/emotion metadata.
    return {"role": "user", "content": json.dumps({"content": text, "language": "zh", "emotion": "😶"}, ensure_ascii=False)}


def history(name):
    return [
        user(f"关闭{name}。"), {"role": "assistant", "content": f"🙂好了，{name}关了。"},
        user(f"打开{name}。"), {"role": "assistant", "content": f"🙂{name}打开了。"},
        user("小七。"), {"role": "assistant", "content": "😊我在呢，咋啦？"},
    ]


def trial(name, action):
    body = {"model": "xiaoqi-home", "stream": True, "messages": history(name) + [user(f"{action}{name}。")]}
    tools, text = [], ""
    with requests.post(HERMES, json=body, headers=HEADERS, stream=True, timeout=90) as resp:
        event = None
        for raw in resp.iter_lines(decode_unicode=True):
            if raw.startswith("event:"):
                event = raw[6:].strip()
            elif raw.startswith("data:") and raw[5:].strip() != "[DONE]":
                data = json.loads(raw[5:])
                if event == "hermes.tool.progress":
                    tools.append(data.get("tool") or data.get("name"))
                else:
                    for choice in data.get("choices", []):
                        text += (choice.get("delta") or {}).get("content") or ""
            elif raw == "":
                event = None
    return sorted(set(t for t in tools if t)), text.strip()


def main():
    _entity, name, trials = sys.argv[1], sys.argv[2], int(sys.argv[3])
    called = 0
    for i in range(trials):
        action = "关闭" if i % 2 == 0 else "打开"
        tools, text = trial(name, action)
        ok = "ha_call_service" in tools
        called += ok
        print(f"{action}{name}: {'CALLED' if ok else 'NO TOOL'} {tools} | {text[:40]}", flush=True)
    print(f"tool called {called}/{trials}")


if __name__ == "__main__":
    main()
