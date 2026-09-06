param([string]$TaskPath = "\VibeTrade\")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Task registration requires Central Standard Time."
}

$taskName = "CisdRetestShadow"
$runner = Join-Path $PSScriptRoot "run_cisd_retest_shadow.ps1"
$qualified = "$($TaskPath.TrimEnd('\'))\$taskName"
$command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`""
& schtasks.exe /Create /TN $qualified /TR $command /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:30 /RI 1 /DU 06:35 /RL LIMITED /F | Out-Host
if ($LASTEXITCODE -ne 0) { throw "schtasks.exe failed for $qualified with exit code $LASTEXITCODE" }
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromSeconds(45)) -MultipleInstances IgnoreNew -StartWhenAvailable
Set-ScheduledTask -TaskName $taskName -TaskPath $TaskPath -Settings $settings | Out-Null
Write-Host "Registered $qualified as completed-bar shadow observation only; no Discord or order authority."
