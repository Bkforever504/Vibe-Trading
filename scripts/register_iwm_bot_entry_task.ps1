Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TaskName = "IWM-Bot-Entry"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_iwm_bot_entry.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""

# Central and Eastern US daylight rules move together. Run once near the start
# of each configured fill-quality window: 09:45 and 15:00 America/New_York.
$TriggerTimes = @("8:45AM", "2:00PM")
$Triggers = foreach ($TriggerTime in $TriggerTimes) {
    New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At $TriggerTime
}

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(20)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Paper options entry at the two configured ET fill-quality windows; all strategy gates remain fail-closed." | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs weekdays at 8:45AM and 2:00PM Central (9:45AM and 3:00PM Eastern)."
Write-Host "The runner pins ALPACA_PAPER=true and preserves all fail-closed entry gates."
