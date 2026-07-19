# Run as Administrator to register FlipBotLearningReport scheduled task.
# Right-click PowerShell -> Run as Administrator, then:
#   .\scripts\register_flip_bot_learning_task.ps1

$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\FlipBotLearningReport"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_flip_bot_learning_report.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -File `"$scriptPath`""

# Runs after ClosedTradePostmortem at 19:15 with enough buffer for slow starts.
$trigger = New-ScheduledTaskTrigger -Daily -At "19:19"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered: $taskName"
Write-Host "Health monitoring is configured in scripts/signal_stack_health_report.py"
