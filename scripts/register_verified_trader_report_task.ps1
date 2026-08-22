# Run as Administrator to register the shadow-only evidence report task.
$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\VerifiedTraderEvidenceReport"
$scriptPath = Join-Path $PSScriptRoot "run_verified_trader_report.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -File `"$scriptPath`""

$trigger = New-ScheduledTaskTrigger -Daily -At "16:20"
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

Write-Host "Registered shadow-only task: $taskName"
