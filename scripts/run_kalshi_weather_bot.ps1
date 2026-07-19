Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

uv run --no-project --with requests --with tzdata python -m strategies.kalshi_weather_bot
if ($LASTEXITCODE -ne 0) {
    throw "Kalshi weather bot failed with exit code $LASTEXITCODE"
}

uv run --no-project python scripts/kalshi_weather_performance_report.py
if ($LASTEXITCODE -ne 0) {
    throw "Kalshi weather performance report failed with exit code $LASTEXITCODE"
}

uv run --no-project python scripts/kalshi_weather_readiness.py
if ($LASTEXITCODE -ne 0) {
    throw "Kalshi weather readiness failed with exit code $LASTEXITCODE"
}
