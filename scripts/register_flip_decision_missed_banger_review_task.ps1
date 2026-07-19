$ErrorActionPreference = "Stop"
$taskName = "\VibeTrade\FlipDecisionMissedBangerReview"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_flip_decision_missed_banger_review.ps1"
$command = "powershell.exe -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`""

schtasks.exe /Create /TN $taskName /TR $command /SC DAILY /ST 19:25 /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Task registration failed with exit code $LASTEXITCODE"
}
Write-Host "Registered: $taskName (read-only, daily at 19:25 CT)"
