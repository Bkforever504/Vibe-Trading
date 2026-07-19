# Claude Handoff - tradermonty/claude-trading-skills Implementation

Project:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Source Evaluated

Repo:
`https://github.com/tradermonty/claude-trading-skills`

Verdict:
- Useful as trading process infrastructure.
- Do not install wholesale into execution.
- Best transferable ideas: IBD distribution-day monitoring and post-trade review discipline.

## What Codex Built

### 1. Distribution Day Scanner

Files:
- `scripts/distribution_day_scanner.py`
- `scripts/run_distribution_day_scanner.ps1`
- `agent/tests/test_distribution_day_scanner.py`

Outputs:
- `data/distribution_day_log.jsonl`
- `~/.vibe-trading/reports/distribution-day-scan.json`

Behavior:
- Uses shared `scripts.market_data.fetch_ohlcv`.
- Alpaca primary, yfinance fallback.
- Scans `QQQ` and `SPY`.
- Distribution day = down day by at least 0.2% on higher volume.
- Counts last 25 sessions.
- Regime:
  - 0-2: normal
  - 3-4: caution
  - 5-6: high
  - 7+: severe

Smoke result on 2026-06-30:
- QQQ: 6 distribution days, high
- SPY: 7 distribution days, severe
- Aggregate: severe

### 2. Closed Trade Postmortem

Files:
- `scripts/closed_trade_postmortem.py`
- `scripts/run_closed_trade_postmortem.ps1`
- `agent/tests/test_closed_trade_postmortem.py`

Outputs:
- `data/closed_trade_postmortem_log.jsonl`
- `~/.vibe-trading/reports/closed-trade-postmortem.json`

Behavior:
- Reads:
  - `~/.vibe-trading/flip-trades.json`
  - `~/.vibe-trading/options-trades.json`
- Scores closed trades on:
  - sizing discipline
  - P&L outcome
  - exit reason
  - stop discipline
  - candidate confidence
  - Market Force alignment if available
- Read-only. No broker calls.

Smoke result on 2026-06-30:
- 0 closed trades for the day, which is expected at run time.

## Market Force Integration

Updated:
- `scripts/market_force_score.py`

New force:
- `institutional`

Source:
- `data/distribution_day_log.jsonl`

Scoring:
- normal: `0.0`
- caution: `-0.75`
- high: `-1.5`
- severe: `-2.0`

Important result:
- Before distribution-day integration, 2026-06-30 Market Force was:
  - `bullish_confirmation`
  - score `+3.0`
  - confidence `7.0`
- After adding institutional distribution pressure:
  - `bullish_lean`
  - score `+1.0`
  - confidence `6.0`
  - coverage `5/6`

This is the desired behavior: intraday breadth is bullish, but heavy recent institutional selling downgrades conviction.

## Reporting Integration

Updated:
- `scripts/signal_stack_health_report.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`

New report rows/sources:
- Distribution Days
- Closed Trade Postmortem

Daily CSV now includes:
- `market_regime_context`
- `trade_review`

## Scheduling

Registered:
- `\VibeTrade\DistributionDayScanner`
  - Weekdays 15:32 local
  - Runs before Market Force Score at 15:40
- `\VibeTrade\ClosedTradePostmortem`
  - Weekdays 19:15 local
  - Runs before leaderboard/CSV EOD jobs

Both tasks:
- Ready

## Verification

Tests:
```powershell
uv run --no-project --with pytest --with pandas --with numpy python -m pytest agent\tests\test_distribution_day_scanner.py agent\tests\test_closed_trade_postmortem.py agent\tests\test_market_force_score.py agent\tests\test_signal_stack_health_report.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py -q
```

Result:
- 22 passed

Compile:
```powershell
uv run --no-project python -m py_compile scripts\distribution_day_scanner.py scripts\closed_trade_postmortem.py scripts\market_force_score.py scripts\signal_stack_health_report.py scripts\signal_stack_leaderboard.py scripts\export_daily_bot_activity_csv.py
```

Result:
- passed

Health after scheduling:
- OK: 8
- stale: 0
- missing: 3
- error: 0

Missing:
- TTM Squeeze
- WaveTrend
- SMC

Expected until their 15:20 first run.

## Operational Boundary

- No live execution changed.
- No order code touched.
- Distribution days and postmortems are observability/process layers only.
- Do not make Market Force or distribution days an execution gate until forward data proves it improves outcomes.

