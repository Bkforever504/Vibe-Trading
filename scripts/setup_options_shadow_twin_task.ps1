$ErrorActionPreference = "Stop"

$TaskName = "VibeTradingOptionsShadowTwin"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_options_shadow_twin.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""

# Central and Eastern US daylight rules move together. These local Central
# triggers cover 09:45 through 15:45 America/New_York.
$TriggerTimes = @(
    "8:45AM", "9:15AM", "9:45AM", "10:15AM", "10:45AM", "11:15AM",
    "11:45AM", "12:15PM", "12:45PM", "1:15PM", "1:45PM", "2:15PM", "2:45PM"
)
$Triggers = foreach ($TriggerTime in $TriggerTimes) {
    New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At $TriggerTime
}

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(10)) `
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
    -Description "Read-only options candidate shadow twin. No order endpoints." | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs weekdays every 30 minutes from 8:45AM through 2:45PM Central."
Write-Host "No order endpoints are imported or called."
