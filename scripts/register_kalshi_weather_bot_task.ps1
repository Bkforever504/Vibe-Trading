Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskName = "KalshiWeatherBot"
$runner = Join-Path $PSScriptRoot "run_kalshi_weather_bot.ps1"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Kalshi weather paper scanner, performance, calibration, and readiness reports" `
    -Force | Out-Null

Write-Output "Registered $taskName every 15 minutes."
