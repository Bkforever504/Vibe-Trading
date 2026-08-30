$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
. (Join-Path $scriptDir "resolve_vibe_python.ps1")
$Python = Get-VibePython
# Run at 09:35 ET daily to accumulate IV history and compute IVR
& $Python scripts/ivr_scanner.py
