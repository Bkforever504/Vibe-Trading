# Register Equity ORB Scout v1 scheduled tasks.
# Run this as Administrator once:
#   .\scripts\register_equity_orb_scout_v1_task.ps1
#
#   EquityOrbScoutV1Entry     Mon-Fri at 10:32 ET  (09:32 CT / 08:32 MT / 07:32 PT)
#   EquityOrbScoutV1Resolve   Mon-Fri at 16:05 ET  (15:05 CT / 14:05 MT / 13:05 PT)

$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Equity ORB Scout v1 task registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$runner = "$repo\scripts\run_equity_orb_scout_v1_shadow.ps1"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$rootFolder = $service.GetFolder("\")
try {
    $null = $service.GetFolder("\VibeTrade")
} catch {
    $null = $rootFolder.CreateFolder("VibeTrade")
}

function Register-Task {
    param(
        [string]$Name,
        [string]$Mode,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger
    )
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -File `"$runner`" -Mode $Mode"
    Register-ScheduledTask `
        -TaskName $Name `
        -TaskPath "\VibeTrade\" `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -RunLevel Limited `
        -Force
    Write-Host "Registered: $Name"
}

# NOTE: local system is CT — 10:32 ET = 09:32 CT. Adjust if your machine tz differs.
$entryTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "09:32"
Register-Task -Name "EquityOrbScoutV1Entry" -Mode "entry" -Trigger $entryTrigger

$resolveTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:05"
Register-Task -Name "EquityOrbScoutV1Resolve" -Mode "resolve" -Trigger $resolveTrigger

Write-Host "Equity ORB Scout v1 tasks registered under \VibeTrade\"
