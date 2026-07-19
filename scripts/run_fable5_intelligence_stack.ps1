$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

Write-Host "Fable 5 Intelligence Stack | manual read-only run"
Write-Host "No live execution. No order routes. Review output before scheduling."
Write-Host ""

uv run --no-project python scripts/strategy_leak_audit.py strategies/flip_bot.py strategies/iwm_options_bot.py --print
python scripts/hmm_regime_scanner.py --print
python scripts/pca_market_forces.py --print
uv run --no-project python scripts/prediction_market_slow_news_watch.py --print
uv run --no-project python scripts/agent_trade_debate_report.py --print
uv run --no-project --with yfinance --with pandas python scripts/missed_banger_review.py
uv run --no-project python scripts/execution_gate_audit.py --print --fail-on-issues
