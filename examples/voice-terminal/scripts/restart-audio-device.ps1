# Restart the driver behind a capture device so Windows sets its audio link up again
# (a Bluetooth headset can keep its mic open while sending only silence). Used as
# [audio] silent_recover_command; needs administrator rights (the task runs as SYSTEM).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restart-audio-device.ps1 -Name "<[audio] input>"
# -Name is the device name as `voice_terminal devices` prints it; * and ? are wildcards.
# -DryRun only prints the device it would restart.
param([Parameter(Mandatory = $true)] [string]$Name, [switch]$DryRun)
$ErrorActionPreference = 'Stop'

# Capture endpoints are SWD\MMDEVAPI\{0.0.1.00000000}.{...}; their parent is the
# driver's device (for a Bluetooth headset, its hands-free audio).
$endpoints = @(Get-PnpDevice -Class AudioEndpoint -PresentOnly | Where-Object {
    $_.FriendlyName -like $Name -and $_.InstanceId -like 'SWD\MMDEVAPI\{0.0.1.*'
  })
if (-not $endpoints) { throw "no capture device named '$Name'" }
foreach ($endpoint in $endpoints) {
  $parent = (Get-PnpDeviceProperty -InstanceId $endpoint.InstanceId -KeyName DEVPKEY_Device_Parent).Data
  if ($DryRun) { "would restart $parent ($((Get-PnpDevice -InstanceId $parent).FriendlyName))"; continue }
  "restarting $parent"
  pnputil /restart-device "$parent"
  if ($LASTEXITCODE -ne 0) { throw "pnputil /restart-device exited $LASTEXITCODE" }
}
