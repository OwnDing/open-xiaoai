"""Install (or upgrade) the official Xiaomi Home integration into /config.

Runs inside the Home Assistant container:

    docker exec homeassistant python3 /opt/xiaoqi-scripts/install_xiaomi_home.py [version]
    docker restart homeassistant

Without a version the latest GitHub release is installed. Where GitHub's
release CDN is slow, download xiaomi_home.zip elsewhere and pass its path:

    docker cp xiaomi_home.zip homeassistant:/tmp/xiaomi_home.zip
    docker exec homeassistant python3 /opt/xiaoqi-scripts/install_xiaomi_home.py /tmp/xiaomi_home.zip
"""

import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "XiaoMi/ha_xiaomi_home"
TARGET = Path("/config/custom_components/xiaomi_home")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "xiaoqi-installer"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else None
    if source and source.endswith(".zip"):
        archive = Path(source).read_bytes()
    else:
        tag = source or json.loads(
            fetch(f"https://api.github.com/repos/{REPO}/releases/latest")
        )["tag_name"]
        archive = fetch(f"https://github.com/{REPO}/releases/download/{tag}/xiaomi_home.zip")

    staging = TARGET.with_name("xiaomi_home.new")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        zipped.extractall(staging)
    if not (staging / "manifest.json").exists():
        raise SystemExit("Unexpected archive layout: manifest.json missing")

    shutil.rmtree(TARGET, ignore_errors=True)
    staging.rename(TARGET)
    version = json.loads((TARGET / "manifest.json").read_text())["version"]
    print(f"Installed Xiaomi Home {version} into {TARGET}; restart Home Assistant.")


if __name__ == "__main__":
    main()
