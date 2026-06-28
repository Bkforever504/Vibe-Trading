# setup_task_scheduler.ps1
# Creates Windows Task Scheduler job to run shadow pullback scanner
# hourly from 10:30 to 15:30 ET on weekdays.
# On Kenny's Central-time Windows machine this is scheduled as 9:30 to 14:30 local.
#
# Run once as Administrator:
#   .\scripts\setup_task_scheduler.ps1
#
# To remove the task later:
#   Unregister-ScheduledTask -TaskName "VibeTradingShadowScanner" -Confirm:$false

$TaskName         = "VibeTradingShadowScanner"
$MomentumTaskName = "MomentumShadowLogger"
$WorkingDir       = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir           = "C:\Users\kenne\.vibe-trading\logs"
$UvPath           = (Get-Command uv -ErrorAction SilentlyContinue).Source

if (-not $UvPath) {
    Write-Error "uv not found in PATH. Install uv first: https://docs.astral.sh/uv/"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Action: uv run ... >> log 2>&1
$ScriptArgs = "run --no-project --with yfinance python strategies/shadow_pullback_signal.py --discord"
$FullCmd    = "cmd /c `"cd /d `"$WorkingDir`" && `"$UvPath`" $ScriptArgs >> `"$LogDir\shadow-scanner.log`" 2>&1`""

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $ScriptArgs >> `"$LogDir\shadow-scanner.log`" 2>&1"

# Triggers: weekdays 9:30-14:30 Central, hourly.
# This matches 10:30-15:30 ET while US Central/Eastern daylight rules move together.
$TriggerTimes = @("9:30AM", "10:30AM", "11:30AM", "12:30PM", "1:30PM", "2:30PM")
$Triggers = foreach ($Time in $TriggerTimes) {
    New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At $Time
}

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(10)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: MNQ first-pullback shadow signal scanner. Paper/shadow only." | Out-Null

$MomentumScriptArgs = "run --no-project --with yfinance python scripts/momentum_shadow_logger.py"
$MomentumAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $MomentumScriptArgs >> `"$LogDir\momentum-shadow.log`" 2>&1"
$MomentumTrigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday `
    -At "8:00AM"

Unregister-ScheduledTask -TaskName $MomentumTaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $MomentumTaskName `
    -Action $MomentumAction `
    -Trigger $MomentumTrigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: weekly ETF momentum rotation shadow logger. No order execution." | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs: weekdays 9:30-14:30 local Central time (10:30-15:30 ET), every 60 minutes"
Write-Host "Log:  $LogDir\shadow-scanner.log"
Write-Host ""
Write-Host "Task registered: $MomentumTaskName"
Write-Host "Runs: Mondays at 8:00AM local Central time"
Write-Host "Log:  $LogDir\momentum-shadow.log"
Write-Host ""
Write-Host "Test run (runs immediately, check log after):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Start-ScheduledTask -TaskName '$MomentumTaskName'"
Write-Host ""
Write-Host "View log:"
Write-Host "  Get-Content '$LogDir\shadow-scanner.log' -Tail 50"
Write-Host ""
Write-Host "View signals:"
Write-Host "  uv run --no-project --with yfinance python scripts/view_shadow_signals.py"
Write-Host "  uv run --no-project --with yfinance python scripts/momentum_shadow_logger.py"
