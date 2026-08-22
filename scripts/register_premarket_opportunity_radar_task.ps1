# Register the read-only premarket opportunity radar. Run elevated once.
$ErrorActionPreference = "Stop"
$TaskName = "PremarketOpportunityRadar"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $WorkingDir "scripts\run_premarket_opportunity_radar.ps1"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
$Triggers = foreach ($Time in @("7:15AM", "7:45AM", "8:10AM", "8:20AM", "8:25AM")) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
}
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) -MultipleInstances IgnoreNew -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Principal $Principal -Description "Vibe-Trading: cross-sector premarket opportunity radar. Alerts only; no orders." | Out-Null
Write-Host "Registered $TaskName (weekdays 7:15, 7:45, 8:10, 8:20, 8:25 AM CT)."
Write-Host "Log: $LogDir\premarket-opportunity-radar.log"
