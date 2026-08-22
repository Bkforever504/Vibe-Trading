# Register the read-only weekday opportunity stream. Run once in PowerShell.
$ErrorActionPreference = "Stop"
$TaskName = "LiveOpportunityEngineReadOnly"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $WorkingDir "scripts\run_live_opportunity_engine.ps1"

if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Runner not found: $Runner"
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "8:25AM"
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromHours(8)) -MultipleInstances IgnoreNew -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Vibe-Trading: read-only Alpaca opportunity stream and completed-bar ranking. No orders." -Force | Out-Null

Write-Host "Registered $TaskName for weekdays at 8:25 AM CT (8-hour limit)."
Write-Host "Manual review only; execution is disabled."
