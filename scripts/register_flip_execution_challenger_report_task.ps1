Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$runner = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_flip_execution_challenger_report.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At "7:24 PM"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskPath "\VibeTrade\" -TaskName "FlipExecutionChallengerReport" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Registered \VibeTrade\FlipExecutionChallengerReport at 19:24 local time."
