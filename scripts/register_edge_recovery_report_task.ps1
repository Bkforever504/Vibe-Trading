$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\EdgeRecoveryReport"
$scriptPath = Join-Path $PSScriptRoot "run_edge_recovery_report.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`""

# Runs after the existing post-close Flip outcome and equity reports.
$trigger = New-ScheduledTaskTrigger -Daily -At "19:32"
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
