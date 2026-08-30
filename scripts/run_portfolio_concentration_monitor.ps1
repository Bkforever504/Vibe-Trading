$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
. (Join-Path $PSScriptRoot "resolve_vibe_python.ps1")
$Python = Get-VibePython
& $Python scripts/portfolio_concentration_monitor.py --print
