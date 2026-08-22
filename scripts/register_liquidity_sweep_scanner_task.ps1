Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Liquidity sweep scanner registration requires Central Standard Time."
}
$runner = "$repo\scripts\run_liquidity_sweep_scanner.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Scanner runner missing: $runner"
}

$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $repo
$triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "8:43AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "9:35AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "10:40AM"
)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 12) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "Liquidity-Sweep-Scanner" `
    -Action $action -Trigger $triggers -Settings $settings `
    -RunLevel Limited -Force | Out-Null
Write-Host "Registered Liquidity-Sweep-Scanner at 08:43, 09:35, and 10:40 CT."
