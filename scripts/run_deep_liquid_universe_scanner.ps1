$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
. (Join-Path $scriptDir "resolve_vibe_python.ps1")
$Python = Get-VibePython
# Read-only broad universe scan. No broker orders are wired.
& $Python scripts/deep_liquid_universe_scanner.py --print
