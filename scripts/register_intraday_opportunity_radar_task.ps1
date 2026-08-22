# Register the read-only market-wide opportunity radar. Run elevated once.
$ErrorActionPreference = "Stop"
$TaskName = "IntradayOpportunityRadar"
$ReviewTaskName = "DailyMoveCoverageReview"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $WorkingDir "scripts\run_intraday_opportunity_radar.ps1"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""

# Forty-eight triggers is the reliable Windows Task Scheduler ceiling. Scan
# faster around the open, then every ten minutes, with a final closing snapshot.
$Times = [System.Collections.Generic.List[string]]::new()
$Cursor = [datetime]::Today.AddHours(8).AddMinutes(35)
$FastEnd = [datetime]::Today.AddHours(10).AddMinutes(20)
while ($Cursor -le $FastEnd) {
    $Times.Add($Cursor.ToString("h:mmtt"))
    $Cursor = $Cursor.AddMinutes(5)
}
$Cursor = [datetime]::Today.AddHours(10).AddMinutes(30)
$SessionEnd = [datetime]::Today.AddHours(14).AddMinutes(30)
while ($Cursor -le $SessionEnd) {
    $Times.Add($Cursor.ToString("h:mmtt"))
    $Cursor = $Cursor.AddMinutes(10)
}
$Times.Add("3:02PM")
$Triggers = foreach ($Time in $Times) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
}
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromMinutes(4)) -MultipleInstances IgnoreNew -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Principal $Principal -Description "Vibe-Trading: market-wide movers/actives discovery with 5m structure and liquidity gates. No orders." | Out-Null

$ReviewAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"Set-Location '$WorkingDir'; python scripts\daily_move_coverage_review.py`""
$ReviewTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:08PM"
Unregister-ScheduledTask -TaskName $ReviewTaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $ReviewTaskName -Action $ReviewAction -Trigger $ReviewTrigger -Settings $Settings -Principal $Principal -Description "Vibe-Trading: end-of-day caught/late/missed market-move accountability. No orders." | Out-Null

Write-Host "Registered $TaskName with $($Times.Count) weekday scans (8:35 AM-3:02 PM CT)."
Write-Host "Registered $ReviewTaskName at 3:08 PM CT."
Write-Host "Log: $LogDir\intraday-opportunity-radar.log"
