# Claude Handoff — go-trader Risk/Status Layer

Date: 2026-06-30
Owner: Codex
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Context

Kenny asked whether `richkuo/go-trader` can help without disturbing the current bot stack. Verdict: useful architecture pattern, not a migration target.

What we extracted:
- portfolio-aware risk visibility
- compact command-center status output
- read-only operational reports

No execution logic was changed.
No live trading gates were added.

## Built

### 1. Portfolio Concentration Monitor

Files:
- `scripts/portfolio_concentration_monitor.py`
- `scripts/run_portfolio_concentration_monitor.ps1`
- `agent/tests/test_portfolio_concentration_monitor.py`

Behavior:
- Calls Alpaca paper account read-only.
- Aggregates current open positions by underlying.
- Estimates simple directional beta exposure for options.
- Flags concentration warnings:
  - `directional_beta_above_3pct_equity`
  - `gross_option_value_above_5pct_equity`
  - `many_underlyings_open`
- Writes:
  - `data/portfolio_concentration_log.jsonl`
  - `~/.vibe-trading/reports/portfolio-concentration.json`

Live smoke result:
- `risk=normal`
- `positions=5`
- `gross=$2302.0 / 2.577% equity`
- `net beta=$909.55 / 1.018% equity`
- Underlyings: TSLA, SPY, IWM

### 2. Bot Status Snapshot

Files:
- `scripts/bot_status_snapshot.py`
- `scripts/run_bot_status_snapshot.ps1`
- `agent/tests/test_bot_status_snapshot.py`

Behavior:
- Reads local reports/logs only; no broker calls.
- Rolls up:
  - signal-stack health
  - Market Force classification
  - Exposure Coach posture
  - portfolio concentration
  - Alpaca/Kalshi guard block counts
  - Flip/IWM open trade counts
  - Daily Outcome Reviewer verdict
- Writes:
  - `data/bot_status_snapshot_log.jsonl`
  - `~/.vibe-trading/reports/bot-status-snapshot.json`

Live smoke result:
- `status=watch`
- `health=missing`
- `market=bullish_lean`
- `exposure=cautious`
- `concentration=normal`
- `account_day_change=516.58`

Important: `watch` is currently because TTM/WaveTrend/SMC close-time logs have not produced first rows yet, not because the new concentration layer found risk.

### 3. Report Integrations

Updated:
- `scripts/signal_stack_health_report.py`
  - Added `Portfolio Risk`
  - Added `Bot Status`
- `scripts/signal_stack_leaderboard.py`
  - Added `Portfolio Concentration`
  - Added `Bot Status Snapshot`
- `scripts/export_daily_bot_activity_csv.py`
  - Added `risk_context`
  - Added `status_review`

CSV smoke:
- `events=54`
- new counts include:
  - `risk_context: 1`
  - `status_review: 1`

### 4. Scheduled Tasks

Created:
- `\VibeTrade\PortfolioConcentrationMonitor`
  - Weekdays 11:05 CT
  - read-only Alpaca concentration report
- `\VibeTrade\BotStatusSnapshot`
  - Weekdays 19:35 CT
  - EOD compact stack status

Both tasks are Ready.

## Verification

Tests:

```powershell
uv run --no-project --with pytest --with pandas --with numpy python -m pytest agent\tests\test_portfolio_concentration_monitor.py agent\tests\test_bot_status_snapshot.py agent\tests\test_signal_stack_health_report.py agent\tests\test_signal_stack_leaderboard.py -q
```

Result:
- `11 passed`

Compile:

```powershell
uv run --no-project python -m py_compile scripts\portfolio_concentration_monitor.py scripts\bot_status_snapshot.py scripts\signal_stack_health_report.py scripts\signal_stack_leaderboard.py scripts\export_daily_bot_activity_csv.py
```

Result:
- passed

Smoke:

```powershell
uv run --no-project --with alpaca-py python scripts\portfolio_concentration_monitor.py --print
uv run --no-project python scripts\bot_status_snapshot.py --print
uv run --no-project python scripts\signal_stack_health_report.py
uv run --no-project python scripts\signal_stack_leaderboard.py
uv run --no-project python scripts\export_daily_bot_activity_csv.py --date 2026-06-30
```

Result:
- all ran successfully

## Current Health Snapshot

After refresh:
- Signal health: `OK=14 STALE=0 MISSING=3 ERROR=0`
- Missing rows are expected until first close-time runs:
  - TTM Squeeze
  - WaveTrend
  - SMC

## Claude Next Checks

1. After 15:20 CT, verify TTM/WaveTrend/SMC produce first rows.
2. After 19:35 CT, verify `BotStatusSnapshot` runs from Task Scheduler and status no longer flags health missing if all close-time rows exist.
3. Do not wire concentration into execution gates yet. Let it log for 1-2 weeks first.
4. If portfolio concentration ever shows `high`, use it as a manual review trigger before changing any bot behavior.

## Safety

This change is read-only/advisory.
No orders are placed.
No strategy entry/exit behavior changed.
No live execution unlocks changed.
