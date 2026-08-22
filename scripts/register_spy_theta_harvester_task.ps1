$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

# Entry: Monday 8:45 AM CT, which is 9:45 AM ET while daylight offsets align.
# The Python entry-window gate remains authoritative and blocks shifted or
# catch-up runs outside 09:40-10:15 ET.
$entryAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$repo\scripts\run_spy_theta_harvester.ps1`""

$entryTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "8:45AM"

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "SPY-Theta-Harvester-Entry" `
    -Action $entryAction `
    -Trigger $entryTrigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered: SPY-Theta-Harvester-Entry (Monday 8:45 AM CT)"

# Monitor confirmed schema-v2 shadow positions from executable close quotes.
$monitorAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$repo\scripts\run_spy_theta_harvester_monitor.ps1`""

$monitorTriggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "9:00AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "10:00AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "11:00AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "12:00PM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "1:00PM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "2:00PM"
)

Register-ScheduledTask `
    -TaskName "SPY-Theta-Harvester-Monitor" `
    -Action $monitorAction `
    -Trigger $monitorTriggers `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered: SPY-Theta-Harvester-Monitor (Mon-Fri hourly 9:00 AM-2:00 PM CT)"
