# Register four MES v2 shadow tasks plus the delayed Databento evidence task.
# Run this script as Administrator once, then Task Scheduler will fire on cadence:
#   MesOrb0932V2Entry       Mon/Wed/Fri at 08:47 CT (09:47 ET)
#   MesOrb0932V2Resolve     Mon/Wed/Fri at 11:05 CT (12:05 ET)
#   MesReopenDriftV2Entry   Mon-Thu at 17:35 CT (18:35 ET)
#   MesReopenDriftV2Resolve Tue-Fri at 07:35 CT (08:35 ET)
#   MesV2DatabentoRegrade   Daily at 12:30 CT (historical-delay regrade)

$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "MES v2 task registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$orb  = "$repo\scripts\run_mes_orb_0932_vix_v2_shadow.ps1"
$rop  = "$repo\scripts\run_mes_reopen_drift_v2_shadow.ps1"
$regrader = "$repo\scripts\run_mes_v2_databento_regrader.ps1"

$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$rootFolder = $service.GetFolder("\")
try {
    $null = $service.GetFolder("\VibeTrade")
} catch {
    $null = $rootFolder.CreateFolder("VibeTrade")
}

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

$regraderSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

function Register-Task {
    param(
        [string]$Name,
        [string]$Script,
        [string]$Argument,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger,
        [Microsoft.Management.Infrastructure.CimInstance]$TaskSettings = $settings
    )
    $modeArgument = if ($Argument) { " -Mode $Argument" } else { "" }
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$Script`"$modeArgument"
    Register-ScheduledTask `
        -TaskName $Name `
        -TaskPath "\VibeTrade\" `
        -Action $action `
        -Trigger $Trigger `
        -Settings $TaskSettings `
        -RunLevel Limited `
        -Force
    Write-Host "Registered: $Name"
}

$mwf = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Wednesday,Friday -At "08:47"
Register-Task -Name "MesOrb0932V2Entry" -Script $orb -Argument "entry" -Trigger $mwf

$mwfResolve = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Wednesday,Friday -At "11:05"
Register-Task -Name "MesOrb0932V2Resolve" -Script $orb -Argument "resolve" -Trigger $mwfResolve

$weeknight = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday -At "17:35"
Register-Task -Name "MesReopenDriftV2Entry" -Script $rop -Argument "entry" -Trigger $weeknight

$morningResolve = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday,Wednesday,Thursday,Friday -At "07:35"
Register-Task -Name "MesReopenDriftV2Resolve" -Script $rop -Argument "resolve" -Trigger $morningResolve

$dailyRegrade = New-ScheduledTaskTrigger -Daily -At "12:30"
Register-Task -Name "MesV2DatabentoRegrade" -Script $regrader -Argument "" -Trigger $dailyRegrade -TaskSettings $regraderSettings

Write-Host "All five MES v2 shadow/evidence tasks registered under \VibeTrade\"
