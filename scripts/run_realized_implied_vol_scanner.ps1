$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo
. (Join-Path $PSScriptRoot "resolve_vibe_python.ps1")
$Python = Get-VibePython

& $Python scripts\realized_implied_vol_scanner.py --print
