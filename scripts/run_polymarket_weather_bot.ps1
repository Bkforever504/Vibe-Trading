$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
uv run --no-project --with requests --with tzdata python strategies/polymarket_weather_bot.py
if ($LASTEXITCODE -ne 0) {
    throw "Polymarket weather bot failed with exit code $LASTEXITCODE"
}
uv run --no-project python scripts/polymarket_weather_performance_report.py
if ($LASTEXITCODE -ne 0) {
    throw "Polymarket weather performance report failed with exit code $LASTEXITCODE"
}
uv run --no-project python scripts/polymarket_weather_live_readiness.py
if ($LASTEXITCODE -ne 0) {
    throw "Polymarket weather live readiness failed with exit code $LASTEXITCODE"
}
