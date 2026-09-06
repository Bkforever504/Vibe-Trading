param(
    [string]$TaskPath = "\VibeTrade\",
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Task registration requires Central Standard Time."
}

$taskName = "CoreIndexTapeWatcher"
$runner = Join-Path $PSScriptRoot "run_core_index_tape_watcher.ps1"
$pythonArgument = if ($PythonPath) { " -PythonPath `"$PythonPath`"" } else { "" }
$qualified = "$($TaskPath.TrimEnd('\'))\$taskName"
$command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"$pythonArgument"

# 08:30-15:05 CT is 09:30-16:05 ET. The one-minute job is deliberately
# independent of the long market-wide wrapper, so an overlapping full scan
# cannot suppress the index tape observations.
& schtasks.exe /Create /TN $qualified /TR $command /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:30 /RI 1 /DU 06:35 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed for $qualified with exit code $LASTEXITCODE"
}

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromSeconds(45)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun
Set-ScheduledTask -TaskName $taskName -TaskPath $TaskPath -Settings $settings | Out-Null

$registered = Get-ScheduledTask -TaskName $taskName -TaskPath $TaskPath
if (-not $registered.Settings.WakeToRun) {
    throw "$qualified registered without WakeToRun"
}
Write-Host "Registered $qualified every minute on weekdays from 08:30 through 15:05 CT."
Write-Host "Shadow alerts only; no option selection or order authority."
