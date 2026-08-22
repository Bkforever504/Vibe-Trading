Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Opportunity intelligence registration requires Central Standard Time."
}
$runner = Join-Path $repo "scripts\run_opportunity_intelligence_pipeline.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Pipeline runner missing: $runner"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday") -At "4:20PM"
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "Opportunity-Intelligence-Pipeline" `
    -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "Registered Opportunity-Intelligence-Pipeline for 4:20 PM CT on weekdays."

