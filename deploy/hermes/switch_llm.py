"""Switch xiaozhi-esp32-server's LLM between direct DeepSeek and Hermes.

Both LLM entries are kept in data/.config.yaml; only selected_module.LLM
changes, so switching back is lossless. A timestamped backup is written first.

    python switch_llm.py hermes      # Xiaozhi -> Hermes -> DeepSeek
    python switch_llm.py deepseek    # Xiaozhi -> DeepSeek (original path)

Paths default to the container layout used by switch-llm.ps1.
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import yaml

DIRECT = "OpenAICompatibleLLM"
HERMES = "HermesAgentLLM"


def read_env(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["hermes", "deepseek"])
    parser.add_argument("--config", default="/xiaozhi-data/.config.yaml")
    parser.add_argument("--hermes-env", default="/hermes/.env")
    parser.add_argument("--hermes-url", default="http://hermes:8642/v1")
    args = parser.parse_args()

    config_path = Path(args.config)
    backup = config_path.with_name(
        f".config.yaml.before-llm-{args.target}-{datetime.now():%Y%m%d-%H%M%S}"
    )
    shutil.copy2(config_path, backup)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    llm = config.setdefault("LLM", {})
    selected = config.setdefault("selected_module", {})

    if args.target == "hermes":
        api_key = read_env(args.hermes_env).get("API_SERVER_KEY")
        if not api_key:
            raise SystemExit(f"API_SERVER_KEY missing in {args.hermes_env}")
        direct = llm.get(DIRECT, {})
        llm[HERMES] = {
            # xiaozhi-provider/hermes.py, mounted by the server compose file:
            # streams from Hermes and retries device commands that answered
            # without calling a tool.
            "type": "hermes",
            "tool_guard": True,
            "base_url": args.hermes_url,
            "model_name": "xiaoqi-home",
            "api_key": api_key,
            "temperature": direct.get("temperature", 0.7),
            "max_tokens": direct.get("max_tokens", 500),
            # Tool calls (search, Home Assistant) can take longer than chat.
            "timeout": {"connect": 3.0, "read": 90.0},
        }
        selected["LLM"] = HERMES
    else:
        if DIRECT not in llm:
            raise SystemExit(f"{DIRECT} is not configured")
        selected["LLM"] = DIRECT

    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"selected_module.LLM = {selected['LLM']} (backup: {backup.name})")


if __name__ == "__main__":
    main()
