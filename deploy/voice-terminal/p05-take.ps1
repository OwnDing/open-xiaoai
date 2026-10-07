# P0.5 test E: record one corpus take from the Bluetooth mic, with spoken
# start / end cues played through the speaker.
param(
  [Parameter(Mandatory)] [string]$Name,
  [int]$Seconds = 130,
  [string]$Mic = '12',
  [string]$Speaker = '11'
)
Set-Location $env:USERPROFILE\voice-terminal
New-Item -ItemType Directory -Force corpus | Out-Null
$py = '.venv\Scripts\python.exe'
$rec = Start-Process -FilePath $py -NoNewWindow -PassThru -RedirectStandardOutput "corpus\$Name.txt" `
  -ArgumentList '-X', 'utf8', 'audio_probe.py', 'record', '--in', $Mic, '--seconds', "$Seconds", '--wav', "corpus\$Name.wav"
Start-Sleep 2
& $py -X utf8 audio_probe.py play --out $Speaker --speech clips\take_start.wav --no-tones | Out-Null
"recording $Name since $(Get-Date -Format HH:mm:ss) for $Seconds s"
$rec.WaitForExit()
& $py -X utf8 audio_probe.py play --out $Speaker --speech clips\take_end.wav --no-tones | Out-Null
Get-Content "corpus\$Name.txt"
