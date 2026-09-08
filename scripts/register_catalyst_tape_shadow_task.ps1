param([string]$TaskPath = "\VibeTrade\", [string]$PythonPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ((Get-TimeZone).Id -ne "Central Standard Time") { throw "Task registration requires Central Standard Time." }

$taskName = "CatalystTapeShadow"
$runner = Join-Path $PSScriptRoot "run_catalyst_tape_shadow.ps1"
$pythonArgument = if ($PythonPath) { " -PythonPath `"$PythonPath`"" } else { "" }
$qualified = "$($TaskPath.TrimEnd('\'))\$taskName"
$command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"$pythonArgument"

# SEC discovery begins at 06:00 ET; tape confirmation naturally stays inactive
# until RTH. The task remains wholly independent from the existing scanner.
& schtasks.exe /Create /TN $qualified /TR $command /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 05:00 /RI 1 /DU 10:05 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) { throw "schtasks.exe failed for $qualified with exit code $LASTEXITCODE" }
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromSeconds(50)) -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun
Set-ScheduledTask -TaskName $taskName -TaskPath $TaskPath -Settings $settings | Out-Null
$registered = Get-ScheduledTask -TaskName $taskName -TaskPath $TaskPath
if (-not $registered.Settings.WakeToRun) { throw "$qualified registered without WakeToRun" }
Write-Host "Registered $qualified every minute on weekdays from 05:00 through 15:05 CT."
Write-Host "Verified-catalyst shadow alerts only; no broker or order authority."
