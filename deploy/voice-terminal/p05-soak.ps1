# P0.5 test B (long): run the soak plan in this session; console output goes to <dir>\console.txt.
param([string]$Plan = 'p05-soak.json', [string]$Dir = "soak\$(Get-Date -Format yyyyMMdd-HHmm)")
Set-Location $env:USERPROFILE\voice-terminal
New-Item -ItemType Directory -Force $Dir | Out-Null
& .venv\Scripts\python.exe -X utf8 audio_probe.py soak --plan $Plan --dir $Dir *>&1 |
  Out-File "$Dir\console.txt" -Encoding utf8
