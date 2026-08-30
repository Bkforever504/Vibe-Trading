param(
    [ValidateSet("entry", "resolve")]
    [string]$Mode = "entry"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
. (Join-Path $PSScriptRoot "resolve_vibe_python.ps1")
$Python = Get-VibePython

& $Python scripts\shadow_alert_runner.py --scanner equity-orb-scout-v1 --mode $Mode
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
