# Register read-only premarket and end-of-day research briefs.
$ErrorActionPreference = "Stop"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $WorkingDir "scripts\run_daily_opportunity_brief.ps1"
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) -MultipleInstances IgnoreNew -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Runner not found: $Runner"
}

$Definitions = @(
    @{ Name = "PremarketOpportunityBriefReadOnly"; Time = "8:22AM"; Period = "premarket" },
    @{ Name = "EndOfDayOpportunityBriefReadOnly"; Time = "3:12PM"; Period = "eod" }
)

foreach ($Definition in $Definitions) {
    $Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`" -Period $($Definition.Period)"
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Definition.Time
    Register-ScheduledTask -TaskName $Definition.Name -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Vibe-Trading: $($Definition.Period) read-only opportunity brief. No orders." -Force | Out-Null
    Write-Host "Registered $($Definition.Name) for weekdays at $($Definition.Time) CT."
}
