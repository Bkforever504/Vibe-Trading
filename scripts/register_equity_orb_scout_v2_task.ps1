# Register Equity ORB Scout v2 (A+ filters) scheduled tasks.
# Run as Administrator once:
#   .\scripts\register_equity_orb_scout_v2_task.ps1

$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Equity ORB Scout v2 task registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$runner = "$repo\scripts\run_equity_orb_scout_v2_shadow.ps1"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
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

# Entry fires 09:33 CT (one minute after v1 to reduce yfinance simultaneous load)
$entryTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "09:33"
Register-Task -Name "EquityOrbScoutV2Entry" -Mode "entry" -Trigger $entryTrigger

# Resolve fires 15:06 CT (one minute after v1)
$resolveTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:06"
Register-Task -Name "EquityOrbScoutV2Resolve" -Mode "resolve" -Trigger $resolveTrigger

Write-Host "Equity ORB Scout v2 tasks registered under \VibeTrade\"
