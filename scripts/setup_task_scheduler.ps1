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
$MesEntryTaskName = "MESReopenVixShadowEntry"
$MesExitTaskName  = "MESReopenVixShadowExit"
$NqLateTaskName   = "NQLateOrbRetestShadow"
$EventGapTaskName = "EventGapContinuationShadow"
$PremarketRadarTaskName = "PremarketOpportunityRadar"
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

# Separate 5-minute late ORB break/retest observation. This candidate is not
# execution-authorized; 15-minute scans preserve timing detail that the legacy
# hourly scanner cannot see.
$NqLateArgs = "run --no-project --with yfinance python scripts/nq_late_orb_retest_shadow.py --print"
$NqLateAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $NqLateArgs >> `"$LogDir\nq-late-orb-retest-shadow.log`" 2>&1"
$NqLateTimes = @(
    "8:45AM", "9:00AM", "9:15AM", "9:30AM", "9:45AM", "10:00AM", "10:15AM", "10:30AM",
    "10:45AM", "11:00AM", "11:15AM", "11:30AM", "11:45AM", "12:00PM", "12:15PM", "12:30PM",
    "12:45PM", "1:00PM", "1:15PM", "1:30PM", "1:45PM", "2:00PM", "2:15PM", "2:30PM"
)
$NqLateTriggers = foreach ($Time in $NqLateTimes) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
}
Unregister-ScheduledTask -TaskName $NqLateTaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $NqLateTaskName `
    -Action $NqLateAction `
    -Trigger $NqLateTriggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: NQ 5m late ORB retest observation. Shadow only; no orders." | Out-Null

# Dynamic large-event gaps need five-minute observation because the first
# causal decision arrives immediately after the completed 15-minute range.
# Social/deep reports discover symbols only; price and volume create signals.
$EventGapRunner = Join-Path $WorkingDir "scripts\run_event_gap_signal_pipeline.ps1"
$EventGapAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$EventGapRunner`""
$EventGapTimes = @(
    "8:45AM", "8:50AM", "8:55AM", "9:00AM", "9:05AM", "9:10AM", "9:15AM", "9:20AM", "9:25AM",
    "9:30AM", "9:35AM", "9:40AM", "9:45AM", "9:50AM", "9:55AM", "10:00AM", "10:05AM", "10:10AM",
    "10:15AM", "10:20AM", "10:25AM", "10:30AM"
)
$EventGapTriggers = foreach ($Time in $EventGapTimes) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
}
Unregister-ScheduledTask -TaskName $EventGapTaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $EventGapTaskName `
    -Action $EventGapAction `
    -Trigger $EventGapTriggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: dynamic event-gap scanner plus bot-readable paper signal contract. No orders." | Out-Null

# Broad premarket discovery runs before the opening bell. It classifies event,
# momentum, and tactical gaps and sends deduplicated watch alerts. A watch is
# never an entry and this process has no broker/order imports.
$PremarketRadarArgs = "run --no-project --with pandas --with requests python scripts/premarket_opportunity_radar.py"
$PremarketRadarAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $PremarketRadarArgs >> `"$LogDir\premarket-opportunity-radar.log`" 2>&1"
$PremarketRadarTriggers = foreach ($Time in @("7:15AM", "7:45AM", "8:10AM", "8:20AM", "8:25AM")) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
}
Unregister-ScheduledTask -TaskName $PremarketRadarTaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $PremarketRadarTaskName `
    -Action $PremarketRadarAction `
    -Trigger $PremarketRadarTriggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: cross-sector premarket opportunity radar. Alerts only; no orders." | Out-Null

$MomentumScriptArgs = "run --no-project --with alpaca-py --with pandas --with yfinance python scripts/momentum_shadow_logger.py"
$MomentumEnsembleArgs = "run --no-project --with pandas --with yfinance python scripts/momentum_edge_ensemble_shadow.py"
$MomentumAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $MomentumScriptArgs >> `"$LogDir\momentum-shadow.log`" 2>&1 && `"$UvPath`" $MomentumEnsembleArgs >> `"$LogDir\momentum-shadow.log`" 2>&1"
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
    -Description "Vibe-Trading: weekly ETF momentum and evidence-ensemble shadow loggers. No order execution." | Out-Null

# Causal, Topstep-session-compliant MES shadow observation. The signal uses
# final 4:00 PM ET inputs, observes the 5:00 PM CT reopen after the first 5m
# bar completes, and resolves from the 9:30 AM ET open bar. No broker imports.
$MesScriptArgs = "run --no-project --with pandas --with yfinance python strategies/mes_reopen_vix_shadow_logger.py"
$MesEntryAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $MesScriptArgs --mode entry >> `"$LogDir\mes-reopen-vix-shadow.log`" 2>&1"
$MesExitAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $MesScriptArgs --mode exit >> `"$LogDir\mes-reopen-vix-shadow.log`" 2>&1"
$MesEntryTrigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday `
    -At "5:06PM"
$MesExitTrigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Tuesday,Wednesday,Thursday,Friday `
    -At "8:36AM"

Unregister-ScheduledTask -TaskName $MesEntryTaskName -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $MesExitTaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $MesEntryTaskName `
    -Action $MesEntryAction `
    -Trigger $MesEntryTrigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: MES 5 PM CT reopen-to-open VIX-filter shadow entry. No order execution." | Out-Null

Register-ScheduledTask `
    -TaskName $MesExitTaskName `
    -Action $MesExitAction `
    -Trigger $MesExitTrigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Vibe-Trading: MES reopen-to-open shadow outcome resolver. No order execution." | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs: weekdays 9:30-14:30 local Central time (10:30-15:30 ET), every 60 minutes"
Write-Host "Log:  $LogDir\shadow-scanner.log"
Write-Host ""
Write-Host "Task registered: $MomentumTaskName"
Write-Host "Runs: Mondays at 8:00AM local Central time"
Write-Host "Log:  $LogDir\momentum-shadow.log"
Write-Host ""
Write-Host "Tasks registered: $MesEntryTaskName, $MesExitTaskName"
Write-Host "Runs: entry Mon-Thu 5:06PM CT; exit Tue-Fri 8:36AM CT"
Write-Host "Log:  $LogDir\mes-reopen-vix-shadow.log"
Write-Host ""
Write-Host "Task registered: $EventGapTaskName"
Write-Host "Runs: weekdays 8:45-10:30AM local Central time, every 5 minutes"
Write-Host "Log:  $LogDir\event-gap-continuation-shadow.log"
Write-Host ""
Write-Host "Task registered: $PremarketRadarTaskName"
Write-Host "Runs: weekdays 7:15, 7:45, 8:10, 8:20, 8:25AM local Central time"
Write-Host "Log:  $LogDir\premarket-opportunity-radar.log"
Write-Host ""
Write-Host "Test run (runs immediately, check log after):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Start-ScheduledTask -TaskName '$MomentumTaskName'"
Write-Host "  Start-ScheduledTask -TaskName '$MesEntryTaskName'"
Write-Host "  Start-ScheduledTask -TaskName '$MesExitTaskName'"
Write-Host "  Start-ScheduledTask -TaskName '$EventGapTaskName'"
Write-Host "  Start-ScheduledTask -TaskName '$PremarketRadarTaskName'"
Write-Host ""
Write-Host "View log:"
Write-Host "  Get-Content '$LogDir\shadow-scanner.log' -Tail 50"
Write-Host ""
Write-Host "View signals:"
Write-Host "  uv run --no-project --with yfinance python scripts/view_shadow_signals.py"
Write-Host "  uv run --no-project --with alpaca-py --with pandas --with yfinance python scripts/momentum_shadow_logger.py"
Write-Host "  uv run --no-project --with pandas --with yfinance python scripts/momentum_edge_ensemble_shadow.py"
