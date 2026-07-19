# Registers the final daily learning-loop closure after all review inputs exist.
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runner = Join-Path $repo "scripts\run_loop_closure_report.ps1"
$log = Join-Path $env:USERPROFILE ".vibe-trading\logs\loop-closure-report.log"
New-Item -ItemType Directory -Force (Split-Path -Parent $log) | Out-Null

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" >> `"$log`" 2>&1"
$trigger = New-ScheduledTaskTrigger -Daily -At "19:59"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName "LoopClosureReport" `
    -TaskPath "\VibeTrade\" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Closes the daily scanner-to-outcome learning chain and persists canonical lessons." `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "Registered \VibeTrade\LoopClosureReport at 19:59"
