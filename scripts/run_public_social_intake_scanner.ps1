$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
# Public/read-only social intake. No logged-in scraping. No broker orders.
uv run --no-project python scripts/public_social_intake_scanner.py --print
