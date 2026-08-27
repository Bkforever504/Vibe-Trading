Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
if ((Get-TimeZone).Id -ne "Central Standard Time") { throw "Detection tasks require Central Standard Time." }
$jobs = @(
  @{ Name = "VibeTradingMoveGroundTruth"; Runner = "run_move_universe_ground_truth.ps1"; At = "4:30PM" },
  @{ Name = "VibeTradingDetectionScorecard"; Runner = "run_detection_scorecard.ps1"; At = "5:15PM" },
  @{ Name = "VibeTradingUniverseCoverageDelta"; Runner = "run_universe_coverage_delta.ps1"; At = "5:20PM" }
)
foreach ($job in $jobs) {
  $runner = Join-Path $repo ("scripts\" + $job.Runner)
  if (-not (Test-Path -LiteralPath $runner)) { throw "Missing runner: $runner" }
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory $repo
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $job.At
  $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $job.Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
}
Write-Host "Registered read-only Phase C detection tasks."
