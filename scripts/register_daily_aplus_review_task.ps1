Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Daily A+ review registration requires Central Standard Time."
}

$runner = Join-Path $repo "scripts\run_daily_aplus_review.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Daily A+ review runner missing: $runner"
}

$pythonPath = (& python -c "import sys; print(sys.executable)").Trim()
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Unable to resolve a stable Python executable for the daily A+ review."
}

$log = Join-Path $env:USERPROFILE ".vibe-trading\logs\daily-aplus-review.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -PythonPath `"$pythonPath`"" `
    -WorkingDirectory $repo
$triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "5:45PM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "7:55PM"
)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName "DailyAPlusReview" `
    -TaskPath "\VibeTrade\" `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Enumerates and audits every A+/top-tier setup, including unresolved outcome follow-up. Read-only; no orders." `
    -Force | Out-Null

Write-Host "Registered \VibeTrade\DailyAPlusReview at 5:45 PM and 7:55 PM CT on weekdays."
