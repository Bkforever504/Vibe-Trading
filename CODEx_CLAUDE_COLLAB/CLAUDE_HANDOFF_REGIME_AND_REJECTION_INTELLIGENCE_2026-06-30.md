# Claude Handoff - Regime Memory + Rejected Trade Intelligence

Date: 2026-06-30
Owner: Codex

## User Request

Kenny asked to improve the intelligence layer, specifically:
- Regime Memory
- Rejected Trade Intelligence

Goal: make the bot smarter every day without making it reckless.

## Built

### 1. Regime Memory

Files:
- `scripts/regime_memory_report.py`
- `scripts/run_regime_memory_report.ps1`
- `agent/tests/test_regime_memory_report.py`

What it does:
- Reads daily outcome reviews and regime/context logs.
- Groups daily results by:
  - Market Force classification
  - breadth status
  - distribution regime
  - sector rotation leadership
  - exposure posture
  - outcome verdict
  - P&L bucket
- Reports:
  - day count
  - total/avg P&L per regime
  - green-day rate
  - guard-block average
  - sample dates

Outputs:
- `data/regime_memory_log.jsonl`
- `~/.vibe-trading/reports/regime-memory.json`

Current first run:
- `days=1`
- `enough_data=false`
- Correctly warns: `LOG BUILDING`
- Current day labels:
  - Market Force: `bullish_lean`
  - Breadth: `uptrend_under_pressure`
  - Distribution: `severe`
  - Exposure: `cautious`

Important:
- Do not use conclusions yet.
- Needs at least 3+ days to become non-empty, ideally 30+ days before changing gates.

### 2. Rejected Trade Intelligence

Files:
- `scripts/rejected_trade_intelligence.py`
- `scripts/run_rejected_trade_intelligence.ps1`
- `agent/tests/test_rejected_trade_intelligence.py`

What it does:
- Reads Alpaca/Kalshi guard block logs.
- Classifies rejected trades by reason and same-day context.
- Verdict labels:
  - `likely_good_rejection`
  - `reasonable_rejection`
  - `possibly_too_strict`
  - `safety_lock`
  - `needs_review`

Outputs:
- `data/rejected_trade_intelligence_log.jsonl`
- `~/.vibe-trading/reports/rejected-trade-intelligence.json`

Current first run:
- `blocks=145`
- verdicts:
  - `likely_good_rejection`: 71
  - `reasonable_rejection`: 55
  - `safety_lock`: 15
  - `needs_review`: 4

Top reasons:
- `confidence_below_minimum`: 55, all reasonable
- `duplicate_symbol_exposure`: 22, likely good
- `portfolio_kill_switch`: 17, likely good
- `live_execution_not_enabled`: 15, safety lock
- `daily_loss_limit`: 15, likely good
- `spread_too_wide`: 13, likely good

Takeaway:
- Guard stack is mostly doing its job.
- No evidence yet to loosen gates.
- `needs_review` bucket is where Claude/Codex should inspect specific records later.

## Reporting Integrations

Updated:
- `scripts/signal_stack_health_report.py`
  - added `Regime Memory`
  - added `Rejected Trades`
- `scripts/signal_stack_leaderboard.py`
  - added `Regime Memory`
  - added `Rejected Trade Intelligence`
- `scripts/export_daily_bot_activity_csv.py`
  - added `intelligence_review` rows

Refresh result:
- Health: `OK=16 STALE=0 MISSING=3 ERROR=0`
- CSV now includes `intelligence_review: 2`
- Leaderboard shows `Rejected Trade Intelligence` fresh/read-only

The 3 missing health rows are still expected first-run close-time logs:
- TTM Squeeze
- WaveTrend
- SMC

## Scheduled Tasks

Created:
- `\VibeTrade\RegimeMemoryReport`
  - weekdays 19:40 CT
- `\VibeTrade\RejectedTradeIntelligence`
  - weekdays 19:45 CT

Both are Ready.

## Verification

Focused tests:

```powershell
uv run --no-project --with pytest python -m pytest agent\tests\test_regime_memory_report.py agent\tests\test_rejected_trade_intelligence.py agent\tests\test_signal_stack_health_report.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py -q
```

Result:
- `14 passed`

Compile:

```powershell
uv run --no-project python -m py_compile scripts\regime_memory_report.py scripts\rejected_trade_intelligence.py scripts\signal_stack_health_report.py scripts\signal_stack_leaderboard.py scripts\export_daily_bot_activity_csv.py
```

Result:
- passed

## Safety

Read-only only.
No bot settings changed.
No guard thresholds changed.
No orders placed.

Future rule:
- `possibly_too_strict` is a research prompt, not permission to loosen gates.
- Regime Memory needs 30+ days before it can become a serious gate candidate.
