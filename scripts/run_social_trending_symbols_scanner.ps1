$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Read-only social trend breadth scan. No broker orders are wired.
uv run --no-project python scripts/social_trending_symbols_scanner.py --limit 30 --print
