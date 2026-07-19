# Claude Handoff — Signal Governance Layer

Date: 2026-06-30  
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## What Codex Built

### 1. Signal Registry

File: `research/signal_registry.json`

Machine-readable registry of every known bot, shadow logger, context scanner, review layer, and governance script.

Important fields per signal:
- `status`
- `execution_enabled`
- `can_submit_orders`
- `broker_or_venue`
- `scheduled_tasks`
- `log_path`
- `evidence_gate`

Key policy:
- Known order-capable scripts:
  - `strategies/flip_bot.py`
  - `strategies/iwm_options_bot.py`
- Known read-only order-history scripts:
  - `strategies/pnl_tracker.py`
  - `strategies/trading_dashboard.py`

Everything else is registered as read-only/context/shadow/review/governance.

### 2. Promotion Rules

File: `rules/signal_promotion_rules.md`

Codifies the rule Kenny has been enforcing:
- 30 trading days
- 10 relevant samples
- improved outcomes
- no overtrading
- reproducible logic
- Codex + Claude review
- Kenny approval before execution-impacting changes

Explicitly forbidden without approval:
- enabling live trading
- raising risk/max contracts
- disabling kill switches
- deleting reset files
- wiring social/X/PMXT/copy-trader signals directly to orders
- treating `possibly_too_strict` as permission to loosen guards

### 3. Execution Gate Audit

Files:
- `scripts/execution_gate_audit.py`
- `scripts/run_execution_gate_audit.ps1`
- `agent/tests/test_execution_gate_audit.py`

Purpose:
- Scan registered scripts for order wiring or live flags.
- Fail if non-execution scripts contain dangerous order patterns.
- Warn if read-only broker clients appear and need human awareness.

Current result:
- `passed=True`
- `signals=44`
- `issues=0`
- `warnings=1`

The one warning is expected:
- `scripts/portfolio_concentration_monitor.py`
- Reason: reads Alpaca positions/account through `TradingClient`
- It is read-only and does not submit orders.

Run:

```powershell
uv run --no-project python scripts\execution_gate_audit.py --print --fail-on-issues
```

### 4. Needs Review Queue

Files:
- `scripts/needs_review_queue.py`
- `scripts/run_needs_review_queue.ps1`
- `agent/tests/test_needs_review_queue.py`

Purpose:
- Converts `rejected_trade_intelligence` output into a short manual review list.
- Queues only `possibly_too_strict` and `needs_review` cases.
- Adds priority, next action, notes, confidence, notional, market-force context, and daily realized P&L.
- Read-only. No guard settings are changed.

Current result:
- `queue=4`
- `source_blocks=145`
- all 4 are low-priority Kalshi dry-run/contract-limit cases from 2026-06-27.

Reports:
- JSONL: `data/needs_review_queue_log.jsonl`
- JSON: `C:\Users\kenne\.vibe-trading\reports\needs-review-queue.json`

Run:

```powershell
uv run --no-project python scripts\needs_review_queue.py --print
```

### 5. Stack Integration

Updated:
- `scripts/signal_stack_health_report.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`
- `research/signal_registry.json`

Health now includes:
- `Needs Review`
- Task: `\VibeTrade\NeedsReviewQueue`
- Log: `data/needs_review_queue_log.jsonl`

Leaderboard now includes:
- `Needs Review Queue`

Daily CSV now includes:
- source: `needs_review_queue`
- event_type: `intelligence_review`

Scheduled task created:
- `\VibeTrade\NeedsReviewQueue`
- Weekdays at 19:50 CT
- Status: Ready

## Verification

Focused tests:

```powershell
uv run --no-project --with pytest python -m pytest agent\tests\test_execution_gate_audit.py agent\tests\test_needs_review_queue.py agent\tests\test_rejected_trade_intelligence.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py -q
```

Result:
- `15 passed`

Health:

```powershell
uv run --no-project python scripts\signal_stack_health_report.py
```

Result:
- `OK=20`
- `STALE=0`
- `MISSING=0`
- `ERROR=0`

Audit:

```powershell
uv run --no-project python scripts\execution_gate_audit.py --print --fail-on-issues
```

Result:
- `passed=True`
- `issues=0`
- `warnings=1`

Daily CSV:

```powershell
uv run --no-project python scripts\export_daily_bot_activity_csv.py --date 2026-06-30
```

Result:
- `events=74`
- output: `C:\Users\kenne\.vibe-trading\reports\daily-bot-activity-2026-06-30.csv`

## Notes For Claude

Do not promote any signal based on this work alone. This is governance, not alpha.

If you evaluate this layer next:
1. Confirm registry entries for newly added scripts stay accurate.
2. Run execution audit after any script that touches Alpaca/Kalshi/Schwab order code.
3. Treat Needs Review Queue as a manual investigation list only.
4. Keep Market Force, social, PMXT, Polymarket, Limitless, and copy-trader outputs observational unless Kenny explicitly approves a gated paper-trading experiment.

## Current State

The system is safer now:
- Every signal has a registry row.
- Promotion rules are written down.
- Source scans catch accidental order wiring.
- Guard-block reviews are visible and scheduled.
- Health report is fully green.

