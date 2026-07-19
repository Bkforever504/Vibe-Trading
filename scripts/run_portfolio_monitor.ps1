$ErrorActionPreference = "Continue"

$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = Join-Path $env:USERPROFILE ".vibe-trading\logs"
$LogFile = Join-Path $LogDir "portfolio-monitor-task.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Repo

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$now = Get-Date
$isWeekday = $now.DayOfWeek -notin @("Saturday", "Sunday")
$start = Get-Date -Hour 8 -Minute 30 -Second 0
$end = Get-Date -Hour 15 -Minute 30 -Second 0
if (-not $isWeekday -or $now -lt $start -or $now -gt $end) {
    "[$timestamp] portfolio_monitor skipped outside market monitor window" | Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 0
}

"[$timestamp] portfolio_monitor start" | Out-File -FilePath $LogFile -Append -Encoding utf8

uv run --no-project --with requests --with python-dotenv python strategies\portfolio_monitor.py >> $LogFile 2>&1
$code = $LASTEXITCODE

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] portfolio_monitor exit=$code" | Out-File -FilePath $LogFile -Append -Encoding utf8
exit $code
