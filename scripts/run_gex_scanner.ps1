$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
. (Join-Path $scriptDir "resolve_vibe_python.ps1")
$Python = Get-VibePython
# Run at 09:35 ET (after open) for intraday GEX levels
& $Python scripts/gex_scanner.py
