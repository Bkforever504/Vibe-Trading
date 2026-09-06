param([string]$PythonPath = "")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location -LiteralPath $repo
. (Join-Path $repo "scripts\resolve_vibe_python.ps1")
$python = Get-VibePython -PythonPath $PythonPath
& $python scripts\premarket_opportunity_radar.py
if ($LASTEXITCODE -ne 0) { throw "premarket radar exited $LASTEXITCODE" }
& $python scripts\premarket_thesis_shadow.py --alert
exit $LASTEXITCODE
