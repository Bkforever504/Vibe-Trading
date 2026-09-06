param(
    [string]$TaskPath = "\VibeTrade\",
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# The workstation runs in Central Time. US Eastern and Central daylight-saving
# transitions are aligned, so 07:00 local is 08:00 ET throughout the year.
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Premarket thesis registration requires the workstation to use Central Standard Time."
}

$taskName = "PremarketThesisNBBOShadow"
$runner = Join-Path $PSScriptRoot "run_premarket_thesis_shadow.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Premarket thesis runner is missing: $runner"
}

$pythonArgument = if ($PythonPath) { " -PythonPath `"$PythonPath`"" } else { "" }
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"$pythonArgument"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "7:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(10)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun

# S4U allows this local, read-only task to run while the user is logged off
# without embedding a password in the registration script. It has no order or
# broker authority; the runner only writes research/report artifacts.
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType S4U `
    -RunLevel Limited

$qualified = "$($TaskPath.TrimEnd('\'))\$taskName"
Unregister-ScheduledTask -TaskName $taskName -TaskPath $TaskPath -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $taskName `
    -TaskPath $TaskPath `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Vibe-Trading: 08:00 ET NBBO premarket thesis, OBSERVE-only. No orders." | Out-Null

Write-Host "Registered $qualified for weekdays at 08:00 ET (07:00 CT), one trigger per day."
Write-Host "Runtime limit: 10 minutes; WakeToRun: enabled; logged-off mode: S4U; order authority: none."
