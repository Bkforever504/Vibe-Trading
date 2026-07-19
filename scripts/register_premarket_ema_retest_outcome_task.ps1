# Run once to register the post-close, read-only EMA outcome evaluator.
$ErrorActionPreference = "Stop"

$taskName = "PremarketEMARetestOutcomes"
$taskPath = "\VibeTrade\"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_premarket_ema_retest_outcome_report.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At "16:20"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force
Write-Host "Registered: $taskPath$taskName"
