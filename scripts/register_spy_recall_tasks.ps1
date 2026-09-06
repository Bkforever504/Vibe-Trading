param(
    [string]$TaskPath = "\VibeTrade\",
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LedgerTaskName = "SpyMoveLedger"
$RecallTaskName = "SpyRecallReport"

$LedgerRunner = Join-Path $PSScriptRoot "run_spy_move_ledger.ps1"
$RecallRunner = Join-Path $PSScriptRoot "run_spy_recall_report.ps1"
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$Folder = $TaskPath.TrimEnd("\")

# Ledger: append qualifying SPY moves every 10 minutes across the RTH session
# plus a final sweep after close. Windows Task Scheduler DAILY /ST /RI /DU is
# equivalent to "start at ST, repeat every RI minutes, for a total duration DU".
# 06:35 CT (07:35 ET premarket close buffer) -> 15:05 CT (16:05 ET post close).
$LedgerQualified = "$Folder\$LedgerTaskName"
$LedgerCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$LedgerRunner`" -PythonPath `"$Python`""
& schtasks.exe /Create /TN $LedgerQualified /TR $LedgerCommand /SC DAILY /ST 08:35 /RI 10 /DU 07:30 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed for $LedgerQualified with exit code $LASTEXITCODE"
}

$LedgerSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun
Set-ScheduledTask -TaskName $LedgerTaskName -TaskPath $TaskPath -Settings $LedgerSettings | Out-Null

$LedgerRegistered = Get-ScheduledTask -TaskName $LedgerTaskName -TaskPath $TaskPath
if (-not $LedgerRegistered.Settings.WakeToRun) {
    throw "$LedgerQualified registered without WakeToRun"
}

# Recall report: run once after close, join ledger vs scanner logs.
$RecallQualified = "$Folder\$RecallTaskName"
$RecallCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RecallRunner`" -PythonPath `"$Python`""
& schtasks.exe /Create /TN $RecallQualified /TR $RecallCommand /SC DAILY /ST 15:30 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed for $RecallQualified with exit code $LASTEXITCODE"
}

$RecallSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(10)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun
Set-ScheduledTask -TaskName $RecallTaskName -TaskPath $TaskPath -Settings $RecallSettings | Out-Null

$RecallRegistered = Get-ScheduledTask -TaskName $RecallTaskName -TaskPath $TaskPath
if (-not $RecallRegistered.Settings.WakeToRun) {
    throw "$RecallQualified registered without WakeToRun"
}

Write-Host "Registered $LedgerQualified every 10 minutes from 08:35 CT for 7h30m."
Write-Host "Registered $RecallQualified daily at 15:30 CT."
Write-Host "Both tasks are context-only. No order authority."
