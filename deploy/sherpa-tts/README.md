# Sherpa-ONNX TTS sidecar

This service exposes Sherpa-ONNX Chinese VITS audio as the raw 24 kHz,
16-bit mono PCM stream expected by `xiaozhi-esp32-server`'s
`index_stream` TTS provider.

The selected voice is `vits-piper-zh_CN-xiao_ya-medium`. The service
resamples its native 22.05 kHz output to the 24 kHz rate used by the
open-xiaoai bridge and emits audio in 60 ms frames.

The MINI deployment keeps the previous EdgeTTS configuration available.
To roll back, set `selected_module.TTS` in `data/.config.yaml` back to
`EdgeTTS` and recreate `xiaozhi-esp32-server`.

## Switching the Open XiaoAI output mode

The bridge supports two output paths:

- `native_xiaomi`: the backend sends text only. The speaker uses Xiaomi's
  built-in `mibrain text_to_speech` voice and plays the generated MP3 with
  `miplayer`. Text is batched, the next segment is prefetched, and temporary
  files are deleted after playback.
- `sherpa`: the backend synthesizes Sherpa-ONNX audio and streams Opus audio
  through the bridge as before.

On the Windows MINI, run the switch script from PowerShell:

```powershell
cd C:\path\to\open-xiaoai\deploy\xiaozhi
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\switch-output-mode.ps1 native_xiaomi
```

To switch back:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\switch-output-mode.ps1 sherpa
```

If `xiaozhi-server` is not located at the script's default sibling path,
pass its Compose directory explicitly with `-ServerDir C:\path\to\xiaozhi-server`.

The script updates the `.env` files for both Compose projects and recreates
the backend first, followed by the bridge. The selected mode therefore
survives Docker and Windows restarts. Valid values are also documented in
each project's `.env.example`.
