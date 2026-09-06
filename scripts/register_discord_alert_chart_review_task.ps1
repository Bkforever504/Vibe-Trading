param(
    [string]$TaskPath = "\VibeTrade\",
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Task registration requires Central Standard Time."
}

$taskName = "DiscordAlertChartReview"
$runner = Join-Path $PSScriptRoot "run_discord_alert_chart_review.ps1"
$pythonArgument = if ($PythonPath) { " -PythonPath `"$PythonPath`"" } else { "" }
$qualified = "$($TaskPath.TrimEnd('\'))\$taskName"
$command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"$pythonArgument"

# 08:40-15:30 CT covers the liquid session plus the final 60-minute outcome
# horizon. It is isolated from the alert path and cannot delay Discord delivery.
& schtasks.exe /Create /TN $qualified /TR $command /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:40 /RI 10 /DU 06:50 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed for $qualified with exit code $LASTEXITCODE"
}

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun
Set-ScheduledTask -TaskName $taskName -TaskPath $TaskPath -Settings $settings | Out-Null

$registered = Get-ScheduledTask -TaskName $taskName -TaskPath $TaskPath
if (-not $registered.Settings.WakeToRun) {
    throw "$qualified registered without WakeToRun"
}
Write-Host "Registered $qualified every 10 minutes on weekdays from 08:40 through 15:30 CT."
Write-Host "Read-only chart outcome audit; isolated from alerts and without order authority."
