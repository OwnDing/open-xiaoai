"""Switch xiaozhi-esp32-server's ASR between SenseVoice on ONNX and PyTorch.

    python switch_asr.py sherpa   # SenseVoiceSmall int8 via sherpa-onnx (~0.2 s)
    python switch_asr.py funasr   # SenseVoiceSmall via FunASR/PyTorch (~0.9 s)

Same model, same accuracy on our tests; the ONNX runtime finishes ~0.65 s
sooner after the user stops speaking. Both entries stay in the config; only
selected_module.ASR changes. A timestamped backup is written first.
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import yaml

FUNASR = "FunASR"
SHERPA = "SherpaASR"
SHERPA_MODEL_DIR = "models/sherpa-onnx-sense-voice"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["sherpa", "funasr"])
    parser.add_argument("--config", default="/xiaozhi-data/.config.yaml")
    args = parser.parse_args()

    config_path = Path(args.config)
    backup = config_path.with_name(
        f".config.yaml.before-asr-{args.target}-{datetime.now():%Y%m%d-%H%M%S}"
    )
    shutil.copy2(config_path, backup)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    asr = config.setdefault("ASR", {})
    selected = config.setdefault("selected_module", {})

    if args.target == "sherpa":
        asr[SHERPA] = {
            "type": "sherpa_onnx_local",
            # Mounted from the host so the model survives container rebuilds.
            "model_dir": SHERPA_MODEL_DIR,
            "model_type": "sense_voice",
            "output_dir": "tmp/",
        }
        selected["ASR"] = SHERPA
    else:
        if FUNASR not in asr:
            raise SystemExit(f"{FUNASR} is not configured")
        selected["ASR"] = FUNASR

    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"selected_module.ASR = {selected['ASR']} (backup: {backup.name})")


if __name__ == "__main__":
    main()
