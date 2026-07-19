$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Run pre-open as context only. No broker orders are wired.
uv run --no-project python scripts/preopen_sentiment_logger.py --print
