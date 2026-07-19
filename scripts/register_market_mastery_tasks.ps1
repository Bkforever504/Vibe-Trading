# Run this script as Administrator to register the Market Mastery scheduled tasks.
# Right-click PowerShell -> Run as Administrator, then:
#   .\scripts\register_market_mastery_tasks.ps1

$ErrorActionPreference = "Stop"

$tasks = @(
    @{
        Name = "\VibeTrade\MarketCatalystCalendar"
        Script = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_market_catalyst_calendar.ps1"
        Time = "08:20"
        Minutes = 5
    },
    @{
        Name = "\VibeTrade\HigherTimeframeMarketMap"
        Script = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_higher_timeframe_market_map.ps1"
        Time = "08:42"
        Minutes = 10
    },
    @{
        Name = "\VibeTrade\KronosMarketForecaster"
        Script = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_kronos_market_forecaster.ps1"
        Time = "08:44"
        Minutes = 20
    },
    @{
        Name = "\VibeTrade\CandlestickContextScanner"
        Script = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_candlestick_context_scanner.ps1"
        Time = "10:07"
        Minutes = 10
    },
    @{
        Name = "\VibeTrade\DailyEdgeOrchestrator"
        Script = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_daily_edge_orchestrator.ps1"
        Time = "10:14"
        Minutes = 10
    }
)

foreach ($task in $tasks) {
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -File `"$($task.Script)`""

    $trigger = New-ScheduledTaskTrigger -Daily -At $task.Time

    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $task.Minutes) `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable:$false

    Register-ScheduledTask `
        -TaskName $task.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -RunLevel Limited `
        -Force

    Write-Host "Registered: $($task.Name) at $($task.Time)"
}

Write-Host "Next: run python scripts\signal_stack_health_report.py and confirm all tasks show Ready."
