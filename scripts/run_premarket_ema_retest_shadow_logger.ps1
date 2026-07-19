$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot
uv run --no-project --with alpaca-py --with pandas --with python-dotenv python scripts/premarket_ema_retest_shadow_logger.py --print
