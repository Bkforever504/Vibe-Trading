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
# Build the causal completed-bar screen before any setup reaches an order gate.
# The report is read-only; a refresh failure aborts the entry run.
python scripts\daily_stock_screener.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\daily_options_universe_ranker.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# Refresh the chronological executable-EV evidence before any setup can reach
# the paper order gate. Missing or non-positive lower bounds fail closed.
python scripts\flip_executable_edge_report.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\sp500_instrument_router.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# Refresh shadow consensus before every entry scan so decisions use today's market regime
python scripts\shadow_consensus_gate.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python strategies\flip_bot.py --entry
exit $LASTEXITCODE
