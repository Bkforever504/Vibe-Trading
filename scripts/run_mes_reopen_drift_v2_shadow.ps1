param(
    [ValidateSet("entry", "resolve")]
    [string]$Mode = "entry"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

uv run --no-project --with yfinance --with pandas --with numpy --with purgedcv==0.1.6 --with arch==8.0.0 --with tsbootstrap==0.7.2 python scripts\shadow_alert_runner.py --scanner mes-reopen-v2 --mode $Mode
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
