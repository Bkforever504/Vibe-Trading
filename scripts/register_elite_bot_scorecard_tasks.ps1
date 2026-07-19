# Registers read-only options research, universe, exit, and readiness tasks.
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $env:USERPROFILE ".vibe-trading\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null

$tasks = @(
    @{
        Name = "OptionsSurfaceIntelligence"
        Time = "19:05"
        Runner = Join-Path $repo "scripts\run_options_surface_intelligence.ps1"
        Log = Join-Path $logDir "options-surface-intelligence.log"
        Description = "Read-only volatility surface and unsigned public-chain intelligence."
    },
    @{
        Name = "DailyOptionsUniverseRanker"
        Time = "19:12"
        Runner = Join-Path $repo "scripts\run_daily_options_universe_ranker.ps1"
        Log = Join-Path $logDir "daily-options-universe-ranker.log"
        Description = "Read-only daily options universe ranking with evidence and liquidity caps."
    },
    @{
        Name = "FlipExitQualityReport"
        Time = "19:17"
        Runner = Join-Path $repo "scripts\run_flip_exit_quality_report.ps1"
        Log = Join-Path $logDir "flip-exit-quality-report.log"
        Description = "Read-only Flip exit-quality analytics."
    },
    @{
        Name = "FlipFeatureAblationReport"
        Time = "19:18"
        Runner = Join-Path $repo "scripts\run_flip_feature_ablation_report.ps1"
        Log = Join-Path $logDir "flip-feature-ablation-report.log"
        Description = "Read-only multiple-testing-corrected Flip feature ablation report."
    },
    @{
        Name = "FlipEquityCurveReport"
        Time = "19:20"
        Runner = Join-Path $repo "scripts\run_flip_equity_curve_report.ps1"
        Log = Join-Path $logDir "flip-equity-curve-report.log"
        Description = "Read-only post-hardening realized PnL curve and drawdown report."
    },
    @{
        Name = "EdgeTrialLedgerReport"
        Time = "19:53"
        Runner = Join-Path $repo "scripts\run_edge_trial_ledger_report.ps1"
        Log = Join-Path $logDir "edge-trial-ledger-report.log"
        Description = "Read-only immutable edge trial and multiple-testing governance report."
    },
    @{
        Name = "EliteBotReadinessScorecard"
        Time = "20:03"
        Runner = Join-Path $repo "scripts\run_elite_bot_readiness_scorecard.ps1"
        Log = Join-Path $logDir "elite-bot-readiness-scorecard.log"
        Description = "Read-only evidence-capped options bot readiness scorecard."
    }
)

foreach ($task in $tasks) {
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$($task.Runner)`" >> `"$($task.Log)`" 2>&1"
    $trigger = New-ScheduledTaskTrigger -Daily -At $task.Time
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask `
        -TaskName $task.Name `
        -TaskPath "\VibeTrade\" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description $task.Description `
        -RunLevel Limited `
        -Force | Out-Null
    Write-Host "Registered \VibeTrade\$($task.Name) at $($task.Time)"
}
