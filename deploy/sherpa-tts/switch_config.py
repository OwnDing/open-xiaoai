from pathlib import Path
from datetime import datetime
import shutil

import yaml


CONFIG_PATH = Path("/opt/xiaozhi-esp32-server/data/.config.yaml")
BACKUP_PATH = CONFIG_PATH.with_name(
    f".config.yaml.before-sherpa-{datetime.now():%Y%m%d-%H%M%S}"
)

shutil.copy2(CONFIG_PATH, BACKUP_PATH)

config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
selected = config.setdefault("selected_module", {})
selected["TTS"] = "SherpaOnnxTTS"

tts = config.setdefault("TTS", {})
tts["SherpaOnnxTTS"] = {
    "type": "index_stream",
    "api_url": "http://sherpa-tts:11996/tts",
    "audio_format": "pcm",
    "voice": "xiao_ya",
    "output_dir": "tmp/",
}

CONFIG_PATH.write_text(
    yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)
print(BACKUP_PATH)
