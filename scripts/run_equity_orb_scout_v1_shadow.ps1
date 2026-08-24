param(
    [ValidateSet("entry", "resolve")]
    [string]$Mode = "entry"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

uv run --no-project --with yfinance --with pandas --with numpy python scripts\shadow_alert_runner.py --scanner equity-orb-scout-v1 --mode $Mode
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
