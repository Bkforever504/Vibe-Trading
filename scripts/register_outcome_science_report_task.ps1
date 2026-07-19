# Run as Administrator to register the daily read-only attribution report.
$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\OutcomeScienceReport"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_outcome_science_report.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At "19:35"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable -RunOnlyIfNetworkAvailable:$false

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force
Write-Host "Registered: $taskName"
