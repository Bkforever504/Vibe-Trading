# Read-only behavioral drift checks at the open, midday, and after the close.
$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\BotBehaviorRegressionWatchdog"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_bot_behavior_regression_watchdog.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -File `"$scriptPath`""
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At "09:50"),
    (New-ScheduledTaskTrigger -Daily -At "12:30"),
    (New-ScheduledTaskTrigger -Daily -At "15:20")
)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable -RunOnlyIfNetworkAvailable:$false

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -RunLevel Limited -Force
Write-Host "Registered: $taskName"
