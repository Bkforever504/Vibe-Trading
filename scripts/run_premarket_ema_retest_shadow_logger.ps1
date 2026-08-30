$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot
. (Join-Path $scriptDir "resolve_vibe_python.ps1")
$Python = Get-VibePython
& $Python scripts/premarket_ema_retest_shadow_logger.py --print
