$ErrorActionPreference = "Stop"

$TaskName = "VibeTradingGarchVolatilityRisk"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_garch_volatility_risk.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""

# Central time. Runs before the options entry window so entries can consume a
# fresh volatility throttle report.
$Triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "8:35AM"
)

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
    -Trigger $Triggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Read-only daily GARCH volatility regime and position-size throttle report. No order endpoints." | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs weekdays at 8:35AM Central before options entries."
Write-Host "No orders are placed; report only."
