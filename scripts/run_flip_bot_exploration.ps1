Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
$env:FLIP_LIVE_EXECUTION_ENABLED = "false"
$env:ENABLE_SHADOW_CONSENSUS_GATE = "true"
$env:ACCELERATED_SHADOW_LEARNING = "true"
$env:SHADOW_EPISODE_INTERVAL_MINUTES = "30"
$env:SHADOW_EPISODE_HORIZON_MINUTES = "60"
$env:FLIP_PAPER_CHALLENGER_SYMBOLS = "SPY,QQQ,AAPL,MSFT,NVDA,TSLA,META,AMZN,SMCI"
$env:FLIP_GAP_CONTINUATION_PAPER_SYMBOLS = "SPY,QQQ,AAPL,MSFT,NVDA,TSLA,META,AMZN,SMCI"
$env:FLIP_ACCOUNT_SIZE_OVERRIDE = "1000"
$env:FLIP_MAX_RISK_PCT = "0.10"
$env:FLIP_EXPLORATION_MAX_NOTIONAL_DOLLARS = "100"
$env:FLIP_MAX_CONTRACTS = "1"
$env:FLIP_MAX_OPEN_POSITIONS = "1"
$env:FLIP_REQUIRE_OPRA_EXECUTION_QUOTES = "true"
$env:FLIP_OPRA_ENTRY_QUOTE_WAIT_SECONDS = "6"
# Keep the process-wide EV gate enabled. The exploration bypass is scoped to
# run_exploration_entry(), so an accidental mode change remains fail closed.
$env:FLIP_EXECUTABLE_EV_GATE_ENABLED = "true"
$env:FLIP_EXPLORATION_MAX_DAILY = "1"
$env:FLIP_EXPLORATION_MAX_OPEN = "1"
Set-Location $repo
# Refresh the causal completed-bar screen and governed universe first.
python scripts\daily_stock_screener.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\daily_options_universe_ranker.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# Refresh instrument router and shadow consensus for signal quality.
# EV report is intentionally skipped; exploration bypasses the EV gate in code.
python scripts\sp500_instrument_router.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\shadow_consensus_gate.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python strategies\flip_bot.py --explore
exit $LASTEXITCODE
