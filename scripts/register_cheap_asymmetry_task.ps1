# Run this script as Administrator to register the CheapAsymmetryScanner scheduled task.
# Right-click PowerShell -> Run as Administrator, then:
#   .\scripts\register_cheap_asymmetry_task.ps1

$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\CheapAsymmetryScanner"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_cheap_asymmetry_scanner.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -File `"$scriptPath`""

# Runs at 19:08 daily (5 min after FlipShadowPnLEvaluator at 19:03)
$trigger = New-ScheduledTaskTrigger -Daily -At "19:08"

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
Write-Host "Next: add health entry in scripts/signal_stack_health_report.py (after confirming task shows Ready)"
