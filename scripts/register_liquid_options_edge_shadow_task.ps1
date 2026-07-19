$ErrorActionPreference = "Stop"

$taskName = "LiquidOptionsEdgeShadow"
$taskPath = "\VibeTrade\"
$runner = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_liquid_options_edge_shadow.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`""
# Machine is America/Chicago: 08:40 through 10:30 maps to 09:40 through 11:30 ET.
$start = [datetime]::Today.AddHours(8).AddMinutes(40)
$triggers = @(0..11 | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $start.AddMinutes($_ * 10) })
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 8) -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Action $action -Trigger $triggers -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "Registered: $taskPath$taskName (read-only shadow evidence, 08:40-10:30 CT)"
