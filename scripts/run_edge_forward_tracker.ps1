# Daily paper forward-tracker runner for passing edge lanes (research only).
$ErrorActionPreference = "Continue"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logDir = "$env:USERPROFILE\.vibe-trading\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$log = Join-Path $logDir "edge-forward-tracker.log"
Set-Location $repo
"=== run $(Get-Date -Format o) ===" | Out-File -Append -Encoding utf8 $log
uv run --no-project --with yfinance --with pandas --with lxml --with pandas-market-calendars python scripts\edge_forward_tracker.py 2>&1 |
    Out-File -Append -Encoding utf8 $log
"=== exit $LASTEXITCODE ===" | Out-File -Append -Encoding utf8 $log
