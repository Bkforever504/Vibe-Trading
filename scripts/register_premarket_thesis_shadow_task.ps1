param([string]$TaskPath = "\VibeTrade\", [string]$PythonPath = "")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ((Get-TimeZone).Id -ne "Central Standard Time") { throw "Task registration requires Central Standard Time." }
$taskName = "PremarketThesisShadow"
$runner = Join-Path $PSScriptRoot "run_premarket_thesis_shadow.ps1"
$pythonArgument = if ($PythonPath) { " -PythonPath `"$PythonPath`"" } else { "" }
$command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"$pythonArgument"
$qualified = "$($TaskPath.TrimEnd('\'))\$taskName"
& schtasks.exe /Create /TN $qualified /TR $command /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:00 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) { throw "schtasks.exe failed for $qualified" }
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun
Set-ScheduledTask -TaskName $taskName -TaskPath $TaskPath -Settings $settings | Out-Null
Write-Host "Registered $qualified at 08:00 ET / 07:00 CT weekdays. OBSERVE-only; no order authority."
