param(
    [string]$TaskPath = "\VibeTrade\",
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$TaskName = "APlusSpotlight"
$Runner = Join-Path $PSScriptRoot "run_aplus_spotlight.ps1"
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$Folder = $TaskPath.TrimEnd("\")
$QualifiedName = "$Folder\$TaskName"
$TaskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -PythonPath `"$Python`""

# Run four minutes behind the market-wide radar. This avoids racing the radar's
# JSONL append while keeping confirmation-to-alert latency below five minutes.
& schtasks.exe /Create /TN $QualifiedName /TR $TaskCommand /SC DAILY /ST 08:39 /RI 5 /DU 06:21 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed with exit code $LASTEXITCODE"
}

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(4)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun
Set-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Settings $Settings | Out-Null

$Registered = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
if (-not $Registered.Settings.WakeToRun) {
    throw "$QualifiedName registered without WakeToRun"
}

Write-Host "Registered $QualifiedName every 5 minutes from 08:39 through 15:00 CT."
Write-Host "Read-only alerts and dashboard refresh only; no order authority."
