# Register the read-only EOD equity continuation and fixed-priority swing observers.
# Run as Administrator once:
#   .\scripts\register_equity_ignition_continuation_shadow_task.ps1

$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Task registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$runner = Join-Path $repo "scripts\run_equity_ignition_continuation_shadow.ps1"
$scanAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Mode scan"
$scanTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:20"
$revalidationAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Mode revalidate"
$revalidationTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "08:42"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$rootFolder = $service.GetFolder("\")
try {
    $null = $service.GetFolder("\VibeTrade")
} catch {
    $null = $rootFolder.CreateFolder("VibeTrade")
}

Register-ScheduledTask `
    -TaskName "EquityIgnitionContinuationShadow" `
    -TaskPath "\VibeTrade\" `
    -Action $scanAction `
    -Trigger $scanTrigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered: \VibeTrade\EquityIgnitionContinuationShadow (weekdays 15:20 CT)"

Register-ScheduledTask `
    -TaskName "EquityIgnitionContinuationRevalidate" `
    -TaskPath "\VibeTrade\" `
    -Action $revalidationAction `
    -Trigger $revalidationTrigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered: \VibeTrade\EquityIgnitionContinuationRevalidate (weekdays 08:42 CT)"
