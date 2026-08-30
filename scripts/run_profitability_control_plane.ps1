$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "resolve_vibe_python.ps1")
$python = Get-VibePython

Push-Location $repo
try {
    & $python "scripts\profitability_control_plane.py"
    if ($LASTEXITCODE -ne 0) {
        throw "profitability control plane failed with exit code $LASTEXITCODE"
    }

    $source = Join-Path $repo "data\profitability_control_plane.json"
    $payload = Get-Content -LiteralPath $source -Raw | ConvertFrom-Json
    if ($payload.can_submit_orders -ne $false -or $payload.execution_enabled -ne $false) {
        throw "control plane unexpectedly claims execution authority"
    }

    $reportDir = Join-Path $HOME ".vibe-trading\reports"
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination (Join-Path $reportDir "profitability-control-plane.json") -Force
}
finally {
    Pop-Location
}
