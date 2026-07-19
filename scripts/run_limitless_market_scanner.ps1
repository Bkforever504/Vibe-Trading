$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Read-only prediction-market venue scan. No API keys or broker orders.
uv run --no-project python scripts/limitless_market_scanner.py --top 10 --min-usd 100 --print
