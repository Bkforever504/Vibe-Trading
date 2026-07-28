Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
Set-Location $repo

python scripts\clear_iwm_residual_position.py --live-read --execute --confirm "CLOSE IWM260807C00315000" --print
