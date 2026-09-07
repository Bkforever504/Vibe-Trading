$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvRoot = Join-Path $env:USERPROFILE ".vibe-trading\prefect-venv"
$Python = Join-Path $VenvRoot "Scripts\python.exe"
$Prefect = Join-Path $VenvRoot "Scripts\prefect.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv $VenvRoot
    & $Python -m pip install "prefect>=3.0,<4.0"
}
$Action = New-ScheduledTaskAction -Execute $Prefect -Argument "server start --host 127.0.0.1 --port 4200" -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit (New-TimeSpan -Days 365)
Register-ScheduledTask -TaskName "VibeTradingPrefectServer" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Local-only Prefect control plane for Vibe Trading shadow workflows" -Force
Write-Output "Registered VibeTradingPrefectServer. Existing scanner tasks remain enabled until the 48-hour acceptance gate passes."
