$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot
uv run --no-project python scripts/prediction_market_microstructure_scanner.py --top 10 --min-usd 100 --print
