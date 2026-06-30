$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
uv run --no-project --with alpaca-py --with pandas --with numpy python scripts/wavetrend_shadow_logger.py
