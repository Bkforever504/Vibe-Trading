Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
$env:FLIP_LIVE_EXECUTION_ENABLED = "false"
$env:ENABLE_SHADOW_CONSENSUS_GATE = "true"
$env:ACCELERATED_SHADOW_LEARNING = "true"
$env:SHADOW_EPISODE_INTERVAL_MINUTES = "30"
$env:SHADOW_EPISODE_HORIZON_MINUTES = "60"
$env:FLIP_PAPER_CHALLENGER_SYMBOLS = "SPY,QQQ"
$env:FLIP_ACCOUNT_SIZE_OVERRIDE = "1000"
$env:FLIP_MAX_RISK_PCT = "0.10"
$env:FLIP_MAX_CONTRACTS = "1"
$env:FLIP_MAX_OPEN_POSITIONS = "1"
$env:FLIP_NOISE_AREA_PAPER_ENABLED = "true"
$env:FLIP_REQUIRE_OPRA_EXECUTION_QUOTES = "true"
$env:FLIP_OPRA_ENTRY_QUOTE_WAIT_SECONDS = "6"
$env:FLIP_EXECUTABLE_EV_GATE_ENABLED = "true"
Set-Location $repo
python scripts\flip_executable_edge_report.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python strategies\flip_bot.py --monitor
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\flip_trade_shape_report.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# Exit-lag protection: while any Flip position is open, keep scanning in-process
# at 60s cadence until ~2 minutes before the next scheduled run. Exits fired at
# -62% against a -30% stop when the bot slept the full 15-minute gap.
python strategies\flip_bot.py --monitor --protect-loop
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# Attribute every newly closed broker trade exactly once. This pipeline is
# read-only with respect to execution and may only nominate shadow challengers.
python scripts\post_trade_learning_cycle.py
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Post-trade learning cycle failed; the next monitor run will retry it."
}
