# Register Monday 17:07 CT autonomous EOD check-in.
# Run as Administrator once:
#   .\scripts\register_monday_checkin_task.ps1
#
# Runs the deterministic read-only EOD reporter and posts to Discord.

$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Monday check-in requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$runner = "$repo\scripts\run_monday_checkin.ps1"

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

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -File `"$runner`""

# Every weekday 17:07 CT (off-minute per scheduler guidance)
$trigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "17:07"

Register-ScheduledTask `
    -TaskName "EodShadowCheckin" `
    -TaskPath "\VibeTrade\" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered: \VibeTrade\EodShadowCheckin — fires weekdays 17:07 CT"
