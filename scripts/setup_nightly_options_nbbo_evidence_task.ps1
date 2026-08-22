$ErrorActionPreference = "Stop"

$TaskName = "VibeTradingNightlyOptionsNBBOEvidence"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_nightly_options_nbbo_evidence.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""
$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "8:15PM"
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
    -Description "Incremental unresolved-candidate OPRA CBBO evidence; max $0.05 per run; no broker orders." | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs weekdays at 8:15PM Central with a hard `$0.05 request ceiling."
Write-Host "No broker order endpoints are imported or called."
