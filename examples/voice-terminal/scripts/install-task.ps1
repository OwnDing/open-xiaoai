# Register one terminal as a Windows scheduled task: starts at boot as SYSTEM
# (session 0, no login or RDP needed), restarted if the process dies.
# Run as an administrator from the voice-terminal directory:
#   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -Config terminal.toml
#   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -Config terminal.toml -Remove
param(
  [string]$Config = 'terminal.toml',
  [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$name = [IO.Path]::GetFileNameWithoutExtension($Config)
$taskName = "OpenXiaoai Voice Terminal ($name)"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
  Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  "removed: $taskName"
}
if ($Remove) { return }

$python = Join-Path $root '.venv\Scripts\python.exe'
$configPath = Join-Path $root $Config
if (-not (Test-Path $python)) { throw "missing $python (run uv sync first)" }
if (-not (Test-Path $configPath)) { throw "missing $configPath" }

$action = New-ScheduledTaskAction -Execute $python -WorkingDirectory $root `
  -Argument "-X utf8 -m voice_terminal run --config `"$configPath`" --log-file `"$root\logs\$name.log`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
  -Settings $settings -Description 'open-xiaoai voice terminal (examples/voice-terminal)' | Out-Null
Start-ScheduledTask -TaskName $taskName
"installed and started: $taskName"
"log: $root\logs\$name.log"
