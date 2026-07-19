$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Read-only broad universe scan. No broker orders are wired.
uv run --no-project --with pandas --with yfinance --with python-dotenv --with alpaca-py python scripts/deep_liquid_universe_scanner.py --print
