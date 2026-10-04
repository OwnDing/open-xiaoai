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

Other devices can share a `native_xiaomi` backend and still get server audio:
list their `Device-Id` values in `XIAOZHI_SERVER_AUDIO_DEVICES`
(comma-separated). Devices not listed, such as the 小爱 bridge, keep getting
text only. The PC voice terminals use this; see
[examples/voice-terminal](../../examples/voice-terminal/README.md).

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

## Switching the ASR runtime

Both options run the same FunASR SenseVoiceSmall model locally:

- `sherpa` (default on the MINI): int8 ONNX through xiaozhi's
  `sherpa_onnx_local` provider. The model lives in
  `models/sherpa-onnx-sense-voice` (`model.int8.onnx`, `tokens.txt`, from
  ModelScope `pengzhendong/sherpa-onnx-sense-voice-zh-en-ja-ko-yue`), mounted
  by `docker-compose.yml`.
- `funasr`: the original PyTorch `fun_local` provider.

```powershell
cd C:\path\to\open-xiaoai\deploy\sherpa-tts
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\switch-asr.ps1 sherpa
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\switch-asr.ps1 funasr
```

Measured on the MINI (`deploy/hermes/bench/asr_bench.py`, text ready after
the end of speech, 2–4 s utterances): PyTorch median 0.88 s, ONNX int8
median 0.24 s with identical transcripts; a 10 s utterance takes 1.70 s vs
0.76 s. The server's memory use drops from about 2.9 GB to 0.6 GB. The ONNX
provider returns plain text, so xiaozhi no longer tags the user's emotion.
