Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Weekly candidate intake registration requires Central Standard Time."
}
$runner = Join-Path $repo "scripts\run_weekly_candidate_intake.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Weekly candidate intake runner missing: $runner"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "9:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "VibeTradingWeeklyCandidateIntake" `
    -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "Registered VibeTradingWeeklyCandidateIntake for Sundays at 9:00 AM CT."
