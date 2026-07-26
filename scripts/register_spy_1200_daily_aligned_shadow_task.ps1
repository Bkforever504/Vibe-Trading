$ErrorActionPreference = "Stop"

$taskName = "SPY1200DailyAlignedShadow"
$taskPath = "\VibeTrade\"
$runner = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_spy_1200_daily_aligned_shadow.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`""

# Machine timezone is America/Chicago. Chicago and New York change daylight
# saving time together, so these remain 12:03/12:08 and 13:03/13:08 ET.
# The second trigger is a transient-data retry; append-only dedupe makes it a
# no-network no-op when the first trigger succeeds.
$signalTrigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(11).AddMinutes(3))
$signalRetryTrigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(11).AddMinutes(8))
$resolveTrigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(12).AddMinutes(3))
$resolveRetryTrigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(12).AddMinutes(8))
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 8) -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Action $action -Trigger @(
    $signalTrigger,
    $signalRetryTrigger,
    $resolveTrigger,
    $resolveRetryTrigger
) -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "Registered: $taskPath$taskName (12:03/12:08 and 13:03/13:08 ET, read-only forward evidence)"
