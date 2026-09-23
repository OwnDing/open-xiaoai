param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("sherpa", "native_xiaomi")]
    [string]$Mode,

    [string]$ServerDir = (
        [IO.Path]::GetFullPath(
            (Join-Path $PSScriptRoot "..\..\..\xiaozhi-server")
        )
    )
)

$ErrorActionPreference = "Stop"
$BridgeDir = $PSScriptRoot

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content -Encoding UTF8 $Path)
    }

    $updated = $false
    $output = foreach ($line in $lines) {
        if ($line -match ("^" + [Regex]::Escape($Name) + "=")) {
            $updated = $true
            "$Name=$Value"
        }
        else {
            $line
        }
    }
    if (-not $updated) {
        $output += "$Name=$Value"
    }
    Set-Content -Encoding Ascii -Path $Path -Value $output
}

if (-not (Test-Path (Join-Path $ServerDir "docker-compose.yml"))) {
    throw "Cannot find xiaozhi-server compose project: $ServerDir"
}

Set-EnvValue (Join-Path $BridgeDir ".env") "XIAOZHI_TTS_OUTPUT_MODE" $Mode
Set-EnvValue (Join-Path $ServerDir ".env") "XIAOZHI_TTS_OUTPUT_MODE" $Mode

Push-Location $ServerDir
try {
    docker compose up -d --force-recreate xiaozhi-esp32-server
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to switch xiaozhi-esp32-server"
    }
}
finally {
    Pop-Location
}

Push-Location $BridgeDir
try {
    docker compose up -d --force-recreate open-xiaoai-xiaozhi
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to switch open-xiaoai-xiaozhi"
    }
}
finally {
    Pop-Location
}

Write-Output "TTS output mode switched to: $Mode"
