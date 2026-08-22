Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
if ((Get-TimeZone).Id -ne "Central Standard Time") { throw "Calibration task requires Central Standard Time." }
$runner = Join-Path $repo "scripts\run_grade_probability_service.ps1"
if (-not (Test-Path -LiteralPath $runner)) { throw "Missing runner: $runner" }
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "8:00AM"
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "VibeTradingGradeCalibration" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "Registered VibeTradingGradeCalibration read-only task for Sunday 8:00 AM CT."
