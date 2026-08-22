Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Phase B task registration requires Central Standard Time."
}

$shortSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$weekdays = @('Monday','Tuesday','Wednesday','Thursday','Friday')

function Register-WeekdayTask([string]$Name, [string]$Runner, [string]$At) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`"" -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $At
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $shortSettings -Principal $principal -Force | Out-Null
}

# One bounded process owns the five-minute cadence, avoiding Task Scheduler's
# 48-trigger limit while preserving the exact required task name.
$reconRunner = Join-Path $repo "scripts\run_broker_reconciliation_daemon.ps1"
$reconAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$reconRunner`" -Window" -WorkingDirectory $repo
$reconTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "09:30"
$reconSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "VibeTradingBrokerReconciliation" -Action $reconAction -Trigger $reconTrigger -Settings $reconSettings -Principal $principal -Force | Out-Null

Register-WeekdayTask "VibeTradingShadowOutcomeResolver" (Join-Path $repo "scripts\run_shadow_outcome_resolver.ps1") "16:30"
Register-WeekdayTask "VibeTradingFillQuality" (Join-Path $repo "scripts\run_fill_quality_report.ps1") "17:00"

Write-Host "Registered Phase B reliability tasks. All payloads remain read-only and order-disabled."
