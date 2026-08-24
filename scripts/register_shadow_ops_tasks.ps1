# Register HMM producer, heartbeat, and Sunday dry-run tasks. Central Time only.
$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Shadow operations task registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$heartbeatRunner = "$repo\scripts\run_shadow_system_heartbeat.ps1"
$preflightRunner = "$repo\scripts\run_sunday_shadow_preflight.ps1"
$hmmRunner = "$repo\scripts\run_hmm_regime_scanner.ps1"

$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$rootFolder = $service.GetFolder("\")
try {
    $null = $service.GetFolder("\VibeTrade")
} catch {
    $null = $rootFolder.CreateFolder("VibeTrade")
}

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

$hmmAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$hmmRunner`""
$hmmTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "08:40"
Register-ScheduledTask `
    -TaskName "HMMRegimeScanner" `
    -TaskPath "\VibeTrade\" `
    -Action $hmmAction `
    -Trigger $hmmTrigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

$heartbeatAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$heartbeatRunner`""
$heartbeatTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At "09:00"),
    (New-ScheduledTaskTrigger -Daily -At "12:00"),
    (New-ScheduledTaskTrigger -Daily -At "15:30")
)
Register-ScheduledTask `
    -TaskName "ShadowSystemHeartbeat" `
    -TaskPath "\VibeTrade\" `
    -Action $heartbeatAction `
    -Trigger $heartbeatTriggers `
    -Settings $settings `
    -RunLevel Limited `
    -Force

$preflightAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$preflightRunner`""
$preflightTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "20:00"
Register-ScheduledTask `
    -TaskName "SundayShadowPreflight" `
    -TaskPath "\VibeTrade\" `
    -Action $preflightAction `
    -Trigger $preflightTrigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered HMMRegimeScanner (08:40 CT), ShadowSystemHeartbeat (09:00/12:00/15:30 CT), and SundayShadowPreflight (Sun 20:00 CT)."
