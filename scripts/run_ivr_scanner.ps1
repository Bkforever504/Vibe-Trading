$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Run at 09:35 ET daily to accumulate IV history and compute IVR
uv run --no-project --with alpaca-py python scripts/ivr_scanner.py
