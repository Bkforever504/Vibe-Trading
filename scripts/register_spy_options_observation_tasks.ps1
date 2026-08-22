Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$timezone = (Get-TimeZone).Id
if ($timezone -ne "Central Standard Time") {
    throw "SPY options task registration requires Central Standard Time; found $timezone"
}

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 12) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

function Register-VibeTask {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][object[]]$Triggers
    )
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$repo\scripts\$Script`""
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Triggers `
        -Settings $settings -RunLevel Limited -Force | Out-Null
    Write-Host "Registered: $Name"
}

$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
$thetaMonitorTriggers = @("9:00AM", "10:00AM", "11:00AM", "12:00PM", "1:00PM", "2:00PM") |
    ForEach-Object { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $_ }
$ironCondorMonitorTriggers = @("9:00AM", "12:00PM", "2:00PM") |
    ForEach-Object { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $_ }
$pmMonitorTriggers = @(
    "11:15AM", "11:30AM", "11:45AM", "12:00PM", "12:15PM", "12:30PM", "12:45PM",
    "1:00PM", "1:15PM", "1:30PM", "1:45PM", "2:00PM", "2:15PM", "2:30PM", "2:45PM"
) | ForEach-Object { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $_ }

Register-VibeTask -Name "SPY-Theta-Harvester-Entry" -Script "run_spy_theta_harvester.ps1" -Triggers @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "8:45AM"
)
Register-VibeTask -Name "SPY-Theta-Harvester-Monitor" -Script "run_spy_theta_harvester_monitor.ps1" -Triggers $thetaMonitorTriggers

Register-VibeTask -Name "SPY-Iron-Condor-Entry" -Script "run_spy_iron_condor.ps1" -Triggers @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "8:45AM"
)
Register-VibeTask -Name "SPY-Iron-Condor-Observation" -Script "run_spy_iron_condor_observation.ps1" -Triggers @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday, Wednesday, Thursday, Friday -At "8:50AM"
)
Register-VibeTask -Name "SPY-Iron-Condor-Monitor" -Script "run_spy_iron_condor_monitor.ps1" -Triggers $ironCondorMonitorTriggers

# Runs after the 09:35-10:30 ET observation window. The output is research
# telemetry only and cannot submit orders or veto a strategy.
Register-VibeTask -Name "Liquidity-Sweep-Scanner" -Script "run_liquidity_sweep_scanner.ps1" -Triggers @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "8:43AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "9:35AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "10:40AM"
)

# 11:05 AM and 12:05 PM CT correspond to 12:05 and 13:05 ET. The second
# observation is intentional: it records a later quote when the first setup is
# unpriceable, while the open-state guard prevents duplicate shadow positions.
Register-VibeTask -Name "SPY-0DTE-PM-Entry" -Script "run_spy_0dte_pm_spread.ps1" -Triggers @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "11:05AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "12:05PM"
)
Register-VibeTask -Name "SPY-0DTE-PM-Monitor" -Script "run_spy_0dte_pm_monitor.ps1" -Triggers $pmMonitorTriggers

Write-Host "SPY options observation schedule registered in Central time."
