$ErrorActionPreference = "Continue"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logDir = Join-Path $HOME ".vibe-trading\logs"
$logPath = Join-Path $logDir "spy-1200-daily-aligned-shadow.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $repo
"=== run $(Get-Date -Format o) ===" | Out-File -Append -Encoding utf8 $logPath
uv run --no-project --python 3.12 --with alpaca-py --with pandas --with numpy --with pyarrow --with requests --with yfinance python scripts\spy_1200_daily_aligned_shadow.py --phase auto 2>&1 |
    Out-File -Append -Encoding utf8 $logPath
$laneExitCode = $LASTEXITCODE
"=== exit $laneExitCode ===" | Out-File -Append -Encoding utf8 $logPath
exit $laneExitCode
