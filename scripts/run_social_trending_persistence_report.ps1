$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Read-only persistence summary for intraday social trend scans.
uv run --no-project python scripts/social_trending_persistence_report.py --days 30 --min-slots 2 --print
