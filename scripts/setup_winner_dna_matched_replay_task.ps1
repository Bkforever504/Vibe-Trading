$ErrorActionPreference = "Stop"

$TaskName = "VibeTradingWinnerDnaMatchedReplay"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_winner_dna_matched_replay.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "8:30AM"
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(20)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Read-only winner-DNA versus losing-twin replay. No order capability." |
    Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs Saturdays at 8:30AM Central."
Write-Host "Read-only research; cannot change strategies or submit orders."

