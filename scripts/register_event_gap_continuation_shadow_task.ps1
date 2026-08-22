# Register only the shadow event-gap collector. Run from an elevated PowerShell.
$ErrorActionPreference = "Stop"

$TaskName = "EventGapContinuationShadow"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$UvPath = (Get-Command uv -ErrorAction SilentlyContinue).Source

if (-not $UvPath) {
    throw "uv not found in PATH"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Runner = Join-Path $WorkingDir "scripts\run_event_gap_signal_pipeline.ps1"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
$Times = [System.Collections.Generic.List[string]]::new()
$Cursor = [datetime]::Today.AddHours(8).AddMinutes(45)
$FastEnd = [datetime]::Today.AddHours(10).AddMinutes(30)
while ($Cursor -le $FastEnd) {
    $Times.Add($Cursor.ToString("h:mmtt"))
    $Cursor = $Cursor.AddMinutes(5)
}

# Continue through the closing session without exceeding Task Scheduler's
# 48-trigger limit. Ten-minute cadence stays inside the signal's 12-minute
# freshness contract while covering late trend and event-continuation moves.
$Cursor = [datetime]::Today.AddHours(10).AddMinutes(40)
$SessionEnd = [datetime]::Today.AddHours(14).AddMinutes(50)
while ($Cursor -le $SessionEnd) {
    $Times.Add($Cursor.ToString("h:mmtt"))
    $Cursor = $Cursor.AddMinutes(10)
}
$Triggers = foreach ($Time in $Times) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
}
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(4)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: dynamic event-gap scanner plus bot-readable paper signal contract. No orders." | Out-Null

Write-Host "Registered $TaskName (weekdays 8:45 AM-2:50 PM CT; 5-minute open cadence, then 10-minute cadence)."
Write-Host "Log: $LogDir\event-gap-continuation-shadow.log"
