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
$env:FLIP_NOISE_AREA_PAPER_ENABLED = "true"
Set-Location $repo
# Refresh shadow consensus before every entry scan so decisions use today's market regime
python scripts\shadow_consensus_gate.py
python strategies\flip_bot.py --entry
