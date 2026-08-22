$ErrorActionPreference = "Stop"

$TaskName = "Vibe-Trading-Remote-Dashboard"
$Supervisor = Join-Path $PSScriptRoot "run_remote_trading_dashboard_supervisor.ps1"
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument (
    "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Supervisor`""
)
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 20 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Keeps the authenticated read-only Vibe-Trading dashboard available." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
