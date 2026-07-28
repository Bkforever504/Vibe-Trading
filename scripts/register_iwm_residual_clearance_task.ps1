Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskName = "IWM-Residual-Clearance"
$runner = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_clear_iwm_residual_position.ps1"
$runAt = [datetime]"2026-07-29 08:32:00"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Once -At $runAt
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "Registered: $taskName at $runAt local time"
