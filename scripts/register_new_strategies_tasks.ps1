Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$timezone = (Get-TimeZone).Id
if ($timezone -ne "Central Standard Time") {
    throw "New strategy task registration requires Central Standard Time; found $timezone"
}
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

$tasks = @(
    @{ Name="SPY-Wheel-Check";          Script="run_spy_wheel.ps1";       Days="Monday,Tuesday,Wednesday,Thursday,Friday"; Time="08:45AM" },
    @{ Name="VIX-Call-Hedge-Check";     Script="run_vix_call_hedge.ps1";  Days="Monday,Tuesday,Wednesday,Thursday,Friday"; Time="09:00AM" },
    @{ Name="SPY-Weekend-Vol-Entry";    Script="run_spy_weekend_vol.ps1"; Days="Thursday";                                 Time="01:35PM" },
    @{ Name="Portfolio-Theta-Dashboard";Script="run_portfolio_theta_dashboard.ps1"; Days="Monday,Tuesday,Wednesday,Thursday,Friday"; Time="09:30AM" }
)

foreach ($t in $tasks) {
    $scriptPath = "$repo\scripts\$($t.Script)"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "Task script missing: $scriptPath"
    }
    $action = New-ScheduledTaskAction -Execute "PowerShell.exe" `
        -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`"" `
        -WorkingDirectory $repo
    $days = $t.Days -split ","
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $t.Time
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
    Write-Host "OK: $($t.Name)"
}

$monitorScript = "$repo\scripts\run_spy_weekend_vol_monitor.ps1"
$monitorAction = New-ScheduledTaskAction -Execute "PowerShell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$monitorScript`"" `
    -WorkingDirectory $repo
$monitorTriggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "01:05PM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "02:05PM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:50AM"
)
Register-ScheduledTask -TaskName "SPY-Weekend-Vol-Monitor" -Action $monitorAction `
    -Trigger $monitorTriggers -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "OK: SPY-Weekend-Vol-Monitor"
Write-Host "Done. All strategy and lifecycle tasks registered."
