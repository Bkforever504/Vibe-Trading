# Claude Handoff - Signal Leaderboard + EOD Ledger - 2026-06-30

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Codex built the integration/reporting layer Kenny requested after the AI-Trader and TradingView execution-repo research.

## Shipped

### 1. Stricter YouTube/social strategy intake template

File:
- `research/social_strategy_intake/youtube_strategy_intake_template.md`

Purpose:
- Prevent social-media strategy claims from bypassing validation.
- Required path:
  `source -> rules -> ambiguity cleanup -> repaint scan -> Python port -> OOS/WF/PBO -> shadow logger -> 30-day review -> paper -> live only after earned confidence`

Includes:
- Source/provenance.
- Exact rules only.
- Ambiguity checklist.
- Repaint/lookahead checks.
- Pine/Python implementation status.
- Backtest gates.
- Forward-test gates.
- Promotion decision.

### 2. Signal stack leaderboard

Files:
- `scripts/signal_stack_leaderboard.py`
- `scripts/run_signal_stack_leaderboard.ps1`
- `agent/tests/test_signal_stack_leaderboard.py`

Report output:
- `~/.vibe-trading/reports/signal-stack-leaderboard.json`

Scheduled task:
- `\VibeTrade\SignalStackLeaderboard`
- Daily at 19:20 CT
- State verified: Ready

What it ranks:
- Flip Bot
- IWM Options Bot
- RSI-2
- KAMA
- Williams %R
- Momentum Rotation
- QQQ/GLD Rotation
- TTM Squeeze
- WaveTrend
- SMC
- GEX
- IVR
- PreOpen Sentiment
- Social Trending
- Limitless Markets

Metrics:
- sample count
- signal/action count
- latest timestamp
- freshness
- execution mode
- average confidence where available
- total P&L where normalized
- win rate where normalized
- max drawdown where normalized
- guard blocked count where available
- rank score

Important interpretation:
- Flip Bot currently ranks poorly because its P&L includes the old oversized June 23 paper loss of about -$11.5k plus the June 29 +$535 winner.
- This is intentional and honest. The leaderboard should not hide the historical risk event.

### 3. Daily bot activity CSV export

Files:
- `scripts/export_daily_bot_activity_csv.py`
- `scripts/run_daily_bot_activity_export.ps1`
- `agent/tests/test_export_daily_bot_activity_csv.py`

CSV output:
- `~/.vibe-trading/reports/daily-bot-activity-YYYY-MM-DD.csv`

Scheduled task:
- `\VibeTrade\DailyBotActivityExport`
- Daily at 19:25 CT
- State verified: Ready

Sources included:
- `~/.vibe-trading/flip-trades.json`
- `~/.vibe-trading/options-trades.json`
- `~/.vibe-trading/guard-blocks.jsonl`
- `~/.vibe-trading/kalshi-guard-blocks.jsonl`
- `data/rsi2_shadow_log.jsonl`
- `data/kama_shadow_log.jsonl`
- `data/williams_r_shadow_log.jsonl`
- `data/momentum_shadow_log.jsonl`
- `data/qqq_gld_shadow_log.jsonl`
- `data/ttm_squeeze_shadow_log.jsonl`
- `data/wavetrend_shadow_log.jsonl`
- `data/smc_shadow_log.jsonl`
- `data/preopen_sentiment_log.jsonl`
- `data/social_trending_symbols_log.jsonl`
- `data/limitless_market_scan_log.jsonl`
- `data/gex_scan_log.jsonl`
- `data/iv_history_log.jsonl`

CSV columns:
- date
- timestamp
- source
- event_type
- strategy
- symbol
- side
- action
- mode
- status
- confidence
- pnl
- reason
- notional
- summary
- raw

Current 2026-06-30 test export:
- `~/.vibe-trading/reports/daily-bot-activity-2026-06-30.csv`
- 10 events:
  - 3 guard blocks
  - 1 sentiment context
  - 2 Limitless context rows
  - 4 social context rows

## Verification

Focused tests:

```powershell
uv run --no-project --with pytest python -m pytest agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py agent\tests\test_signal_stack_health_report.py agent\tests\test_social_trending_symbols_scanner.py agent\tests\test_social_trending_persistence_report.py agent\tests\test_limitless_market_scanner.py agent\tests\test_preopen_sentiment_logger.py -q
```

Result:
- `23 passed`

Manual runs:

```powershell
uv run --no-project python scripts\signal_stack_leaderboard.py
uv run --no-project python scripts\export_daily_bot_activity_csv.py --date 2026-06-30
```

Both ran cleanly.

## Safety

- Both new scripts are read-only.
- No broker calls.
- No orders.
- No execution gates changed.
- This is observability/reporting only.

## Next Ideas

P1:
- Add normalized hypothetical P&L to RSI-2/KAMA/Williams/QQQ-GLD loggers once enough forward rows exist.

P1:
- Add `run_signal_stack_leaderboard.ps1` and `run_daily_bot_activity_export.ps1` to any master EOD checklist docs if maintained.

P2:
- Build optional HTML view over `signal-stack-leaderboard.json` and daily CSV for Kenny.
