# Copy the wake-word and VAD models from the XiaoAi bridge container and synthesize
# the voice prompts ("wo zai" etc.) in the voice the backend answers in. Run on the
# Docker host:
#   powershell -ExecutionPolicy Bypass -File scripts\fetch-assets.ps1
#   ... -PromptEngine sherpa      # WAV prompts in the Sherpa voice instead of Edge MP3
param(
  [string]$BridgeContainer = 'open-xiaoai-xiaozhi',
  [string]$BackendContainer = 'xiaozhi-esp32-server',
  [ValidateSet('edge', 'sherpa')] [string]$PromptEngine = 'edge',
  [string]$Voice = 'zh-CN-XiaoxiaoNeural'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force "$root\models\kws", "$root\prompts" | Out-Null

function Invoke-Docker {
  & docker @args
  if ($LASTEXITCODE -ne 0) { throw "docker $($args -join ' ') failed" }
}

foreach ($file in 'tokens.txt', 'encoder.onnx', 'decoder.onnx', 'joiner.onnx', 'bpe.model') {
  Invoke-Docker cp "${BridgeContainer}:/app/xiaozhi/models/$file" "$root\models\kws\$file"
}
Invoke-Docker cp "${BridgeContainer}:/app/xiaozhi/models/silero_vad.onnx" "$root\models\silero_vad.onnx"

Invoke-Docker cp "$PSScriptRoot\make_clips.py" "${BackendContainer}:/tmp/make_clips.py"
Invoke-Docker exec $BackendContainer python /tmp/make_clips.py /tmp/vt-prompts prompts --engine $PromptEngine --voice $Voice
$ext = if ($PromptEngine -eq 'edge') { 'mp3' } else { 'wav' }
foreach ($name in 'wake', 'no_reply', 'goodbye') {
  Invoke-Docker cp "${BackendContainer}:/tmp/vt-prompts/$name.$ext" "$root\prompts\$name.$ext"
}
"prompts: $PromptEngine ($ext) - point [session] *_prompt in the terminal config at prompts\*.$ext"
Invoke-Docker exec $BackendContainer rm -rf /tmp/vt-prompts /tmp/make_clips.py

Get-ChildItem -Recurse -File "$root\models", "$root\prompts" | ForEach-Object { '{0,12:N0}  {1}' -f $_.Length, $_.FullName }
