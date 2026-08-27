Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "CISD tracker registration expects the dashboard host in Central Time."
}

$python = (Get-Command python.exe -ErrorAction Stop).Source
$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

function Register-CisdTask([string]$Name, [string]$Script, [string]$CentralTime) {
    $scriptPath = Join-Path $repo ("scripts\" + $Script)
    if (-not (Test-Path -LiteralPath $scriptPath)) { throw "Missing CISD task script: $scriptPath" }
    $action = New-ScheduledTaskAction `
        -Execute $python `
        -Argument "`"$scriptPath`"" `
        -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $CentralTime
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
}

# Host is Central Time; these correspond to 16:10, 16:20, and 16:30 ET.
# Previously the resolver ran at 15:35 CT (an hour after the 15:00 close),
# which serialized the close-of-day evidence into the evening review window
# and left less than four hours before overnight reports fired. Pulled forward
# to run immediately after the aggregator so the outcome ledger and promotion
# gate finish before the health snapshot at 15:40 CT. Ordering is enforced by
# market_schedule_alignment.ORDER_CHECKS.
Register-CisdTask "PatternGrader-OutcomeResolver" "pattern_grader_outcome_resolver.py" "15:10"
Register-CisdTask "CISD-PromotionTracker" "cisd_promotion_tracker.py" "15:20"
Register-CisdTask "PromoteValidatedPatterns" "promote_validated_patterns.py" "15:30"

Write-Host "Registered CISD outcome -> tracker -> promotion chain. All tasks remain non-execution."
