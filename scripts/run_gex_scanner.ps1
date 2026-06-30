$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Run at 09:35 ET (after open) for intraday GEX levels
uv run --no-project --with alpaca-py python scripts/gex_scanner.py
