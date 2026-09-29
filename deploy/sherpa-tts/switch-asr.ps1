param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("sherpa", "funasr")]
    [string]$Target,

    [string]$ServerDir
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 leaves $PSScriptRoot empty inside param() defaults.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ServerDir) {
    $ServerDir = [IO.Path]::GetFullPath(
        (Join-Path $ScriptDir "..\..\..\xiaozhi-server")
    )
}
$DataDir = Join-Path $ServerDir "data"

if (-not (Test-Path (Join-Path $DataDir ".config.yaml"))) {
    throw "Cannot find xiaozhi-server config: $DataDir\.config.yaml"
}

docker run --rm `
    -v "${DataDir}:/xiaozhi-data" `
    -v "${ScriptDir}:/scripts:ro" `
    --entrypoint python `
    local/xiaozhi-esp32-server:smooth-audio `
    /scripts/switch_asr.py $Target
if ($LASTEXITCODE -ne 0) {
    throw "Failed to update xiaozhi-server ASR config"
}

docker restart xiaozhi-esp32-server
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restart xiaozhi-esp32-server"
}

Write-Output "Xiaozhi ASR switched to: $Target"
