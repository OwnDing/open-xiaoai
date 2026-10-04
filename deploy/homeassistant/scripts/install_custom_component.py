"""Install a Home Assistant custom integration from a downloaded archive.

GitHub release downloads time out on the MINI, so archives are fetched
elsewhere, copied into the container, and installed with:

    docker cp hacs.zip homeassistant:/tmp/hacs.zip
    docker exec homeassistant python3 /opt/xiaoqi-scripts/install_custom_component.py hacs /tmp/hacs.zip
    docker restart homeassistant

Works with release zips whose root is the integration (hacs.zip) and with
source archives containing custom_components/<domain> (GitHub tarballs).
The integration is located by the `domain` in its manifest.json.
"""

import io
import json
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

CUSTOM_COMPONENTS = Path("/config/custom_components")


def extract(archive: Path, target: Path):
    data = archive.read_bytes()
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:
            zipped.extractall(target)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as tarred:
            tarred.extractall(target, filter="data")


def find_integration(root: Path, domain: str) -> Path:
    for manifest in sorted(root.rglob("manifest.json"), key=lambda p: len(p.parts)):
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("domain") == domain:
                return manifest.parent
        except (ValueError, OSError):
            continue
    raise SystemExit(f"No manifest.json with domain {domain!r} in the archive")


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    domain, archive = sys.argv[1], Path(sys.argv[2])
    with tempfile.TemporaryDirectory() as tmp:
        extract(archive, Path(tmp))
        source = find_integration(Path(tmp), domain)
        target = CUSTOM_COMPONENTS / domain
        staging = target.with_name(f"{domain}.new")
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(source, staging)
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    version = json.loads((target / "manifest.json").read_text(encoding="utf-8")).get("version")
    print(f"Installed {domain} {version} into {target}; restart Home Assistant.")


if __name__ == "__main__":
    main()
