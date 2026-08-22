# Register the Flip-Bot-Exploration scheduled task.
# Run as Administrator:
#   .\scripts\register_flip_exploration_task.ps1

$ErrorActionPreference = "Stop"

$taskName = "Flip-Bot-Exploration"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_flip_bot_exploration.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`""

# Retry through the ORB and trend-entry windows. The lane still submits at most
# one paper trade per day and never bypasses quality, slippage, or safety gates.
$triggers = @(
    "8:40AM", "9:00AM", "9:20AM", "9:40AM", "10:00AM", "10:20AM",
    "10:40AM", "11:00AM", "11:20AM", "11:40AM", "12:00PM", "12:20PM"
) | ForEach-Object {
    New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At $_
}

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -StartWhenAvailable `
    -WakeToRun `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered: $taskName"
Write-Host "Schedule : Mon-Fri every 20 minutes, 8:40 AM-12:20 PM CT"
Write-Host "Script   : $scriptPath"
Write-Host "Hardening: run scripts\harden_flip_bot_scheduler.ps1 and add '$taskName' to its taskNames list"
