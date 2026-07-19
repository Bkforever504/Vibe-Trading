# Run this script as Administrator to register the ShadowConsensusGate scheduled task.
# Right-click PowerShell -> Run as Administrator, then:
#   .\scripts\register_shadow_consensus_gate_task.ps1

$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\ShadowConsensusGate"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_shadow_consensus_gate.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -File `"$scriptPath`""

# Runs at 10:12 daily, after AdaptiveOptionsShadowPlaybook at 10:10.
$trigger = New-ScheduledTaskTrigger -Daily -At "10:12"

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
