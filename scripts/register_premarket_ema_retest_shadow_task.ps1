# Run from an elevated PowerShell session when Task Scheduler registration is
# locked down.  The task is intentionally weekday-only because the scanner
# depends on US equity-session data.
$ErrorActionPreference = "Stop"

$taskName = "PremarketEMARetestShadow"
$taskPath = "\VibeTrade\"
$scriptPath = Join-Path $PSScriptRoot "run_premarket_ema_retest_shadow_logger.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`""

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "10:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false
$settings.WakeToRun = $true

Register-ScheduledTask `
    -TaskName $taskName `
    -TaskPath $taskPath `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "Registered $taskPath$taskName for weekdays at 10:00 CT."
