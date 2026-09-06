# Register the read-only market-wide opportunity radar. Run elevated once.
$ErrorActionPreference = "Stop"
$TaskName = "IntradayOpportunityRadar"
$ReviewTaskName = "DailyMoveCoverageReview"
$PreopenTaskName = "IntradayRadarPreopenCoverage"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $WorkingDir "scripts\run_intraday_opportunity_radar.ps1"
$PreopenRunner = Join-Path $WorkingDir "scripts\run_premarket_readiness.ps1"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""

# Forty-eight triggers is the reliable Windows Task Scheduler ceiling. Scan
# faster around the open, then every ten minutes, without leaving a >15-minute
# blind spot into the close.
$Times = [System.Collections.Generic.List[string]]::new()
$Cursor = [datetime]::Today.AddHours(8).AddMinutes(35)
$FastEnd = [datetime]::Today.AddHours(10).AddMinutes(5)
while ($Cursor -le $FastEnd) {
    $Times.Add($Cursor.ToString("h:mmtt"))
    $Cursor = $Cursor.AddMinutes(5)
}
$Cursor = [datetime]::Today.AddHours(10).AddMinutes(15)
$SessionEnd = [datetime]::Today.AddHours(14).AddMinutes(45)
while ($Cursor -le $SessionEnd) {
    $Times.Add($Cursor.ToString("h:mmtt"))
    $Cursor = $Cursor.AddMinutes(10)
}
$Times.Add("3:00PM")
$Triggers = foreach ($Time in $Times) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
}
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromMinutes(10)) -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Principal $Principal -Description "Vibe-Trading: market-wide movers/actives, BBR context, and raw-chart follow-through audit. No orders." | Out-Null

# One pre-open snapshot verifies the reserved liquid core before the opening
# move. It only writes the same read-only radar report and coverage trace.
$PreopenAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PreopenRunner`""
$PreopenTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "8:25AM"
Unregister-ScheduledTask -TaskName $PreopenTaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $PreopenTaskName -Action $PreopenAction -Trigger $PreopenTrigger -Settings $Settings -Principal $Principal -Description "Vibe-Trading: pre-open radar, time-matched RVOL, SEC provenance, dashboard, and fail-closed readiness gate. Read-only; no orders." | Out-Null

$ReviewAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"Set-Location '$WorkingDir'; python scripts\daily_move_coverage_review.py`""
$ReviewTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:08PM"
Unregister-ScheduledTask -TaskName $ReviewTaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $ReviewTaskName -Action $ReviewAction -Trigger $ReviewTrigger -Settings $Settings -Principal $Principal -Description "Vibe-Trading: end-of-day caught/late/missed market-move accountability. No orders." | Out-Null

Write-Host "Registered $TaskName with $($Times.Count) weekday scans (8:35 AM-3:00 PM CT; max gap 15 minutes)."
Write-Host "Registered $ReviewTaskName at 3:08 PM CT."
Write-Host "Registered $PreopenTaskName at 8:25 AM CT."
Write-Host "Log: $LogDir\intraday-opportunity-radar.log"
