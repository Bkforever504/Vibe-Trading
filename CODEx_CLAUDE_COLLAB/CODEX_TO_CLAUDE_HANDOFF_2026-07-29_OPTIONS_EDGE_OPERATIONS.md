# Codex to Claude Code Handoff - Options Edge Operations

Date: 2026-07-29
Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Mode: paper trading, evidence-driven, fail-closed

## Operator Summary

Codex implemented the six requested options-selling edge filters and verified the active options safety lane. The system is operationally clean, but options entries remain correctly blocked until broker reconciliation clears the unexplained IWM residual.

Do not claim proven profitability from this state. The process is hardened, the guards are working, and the next edge comes from clean forward evidence.

## New Commits

- `6033fc4` - Raise options credit quality floor
- `b20b09c` - Gate options entries to fill-quality windows
- `b1b1ebf` - Roll iron condors at management DTE
- `4071ee7` - Use strategy-specific IV rank gates
- `b67c5f0` - Require IV premium over realized volatility
- `8dc8292` - Apply strategy-specific VIX bands

These are on top of:

- `f09e641` - Add July 29 options hardening handoff
- `0bde9fa`, `343264b`, `72f7bf4`, `d9dba5e`, `68db0bf`

## Implemented Edge Filters

File: `strategies/iwm_options_bot.py`

- Credit quality:
  - Source default `MIN_CREDIT_TO_RISK=0.33`
  - Local ignored `agent/.env` also set to `0.33`
- Entry windows:
  - `OPTIONS_ENTRY_WINDOWS_ET=09:45-10:30,15:00-15:45`
  - Monitoring still runs outside these windows; only new entries are blocked.
- Stop and IC management:
  - `STOP_LOSS_PCT=-1.0`
  - `IC_DTE_MANAGE_DAYS=21`
  - 21-DTE iron condors attempt a tested-side roll instead of a full group close.
  - Roll path remains fail-closed if tested side, quotes, replacement chain, or broker fill proof is missing.
- IV Rank gates:
  - IC: `IC_IV_RANK_MIN=50`
  - PS/CS: `SPREAD_IV_RANK_MIN=35`
  - Wheel: `WHEEL_IV_RANK_MIN=45`
- IV over realized vol edge:
  - `ENABLE_IV_REALIZED_VOL_EDGE=true`
  - `IV_REALIZED_VOL_WINDOW=30`
  - `IV_OVER_REALIZED_MIN_RATIO=1.05`
  - Entries skip with `iv_not_overpriced_vs_realized` when implied vol is not at least 1.05x realized vol.
- VIX bands:
  - Broad premium-selling gate: `VIX_MIN=14`, `VIX_MAX=35`
  - IC: `IC_VIX_MIN=16`, `IC_VIX_MAX=28`
  - PS/CS/wheel: `SPREAD_VIX_MIN=14`, `SPREAD_VIX_MAX=35`

## Safety Flags Observed

From local ignored `agent/.env`, redacted for secrets:

- `ALPACA_PAPER=true`
- `REQUIRE_MANUAL_APPROVAL=false`
- `AUTO_CLOSE_GROUPS=true`
- `MAX_TRADES_PER_DAY=6`
- `MAX_OPEN_TRADES_PER_UNDERLYING=2`

Do not set live execution flags. Do not bypass reconciliation.

## Current Execution Blocker

Read-only reconciler result:

```text
Options Position Reconciler
generated_at: 2026-07-29T06:09:01Z
status: review_required
entries_allowed: False
finding: unexplained broker residual IWM260807C00315000 qty=+2
repair plan: investigate_unexplained_residual, requires Kenny approval
```

This is the sole options-entry blocker. It is correct for the bot to refuse new options entries until the broker residual is gone and reconciliation reports `entries_allowed=True`.

Scheduled task:

- `IWM-Residual-Clearance`
- LastRunTime: `11/30/1999 12:00:00 AM`
- LastTaskResult: `267011`
- NextRunTime: `7/29/2026 8:32:00 AM`

The 1999 timestamp means the one-shot task has not run yet, not that it failed after running.

## Scheduler State

Main active stack is registered and `Ready`. Recent last results are `0` for core tasks, including:

- `Flip-Bot-Entry`
- `Flip-Bot-Monitor`
- `Flip-Bot-Trend-Entry`
- `IWM-Bot-Entry`
- `IWM-Bot-Monitor`
- `VibeTradingGarchVolatilityRisk`
- `LiquidOptionsEdgeShadow`
- `VibeTradingOptionsShadowTwin`
- `ShadowConsensusGate`
- `MarketScheduleAlignment`
- `SignalStackHealthReport`
- `VibeTrading-Portfolio-Monitor`

Disabled tasks observed:

- `PolymarketWeatherBot` is disabled with missed runs.
- `VibeTradingNinjaTraderMESSim` is disabled.

Do not enable disabled tasks blindly. Confirm intent and execution surface first.

## Read-Only Report Results

Options context stack passed:

```text
GARCH refreshed
Options liquidation heatmap refreshed
Adaptive options shadow playbook refreshed
Options quant risk budget refreshed
```

GARCH snapshot:

```text
ok=7
storm=QQQ,NVDA,AAPL,TSLA,PLTR
SPY normal mult=1.0
IWM calm mult=0.825
TSLA storm mult=0.25
PLTR storm mult=0.25
```

Quant risk budget:

```text
samples=13
groups=18
global_cap=0.0
global sortino=-0.2728
put_spread sortino=-0.3751
No orders placed. Output is a sizing throttle only.
```

Schedule alignment:

```text
passed=True
aligned=56/56
issues=0
warnings=2
```

Warnings are extra monitor start times for `Flip-Bot-Monitor` and `IWM-Bot-Monitor`; they are informational because monitor tasks are risk-reducing/read-only unless exits trigger.

Execution gate audit:

```text
passed=True
signals=100
issues=0
warnings=1
```

Warning is the known read-only broker-client verification warning for `portfolio_concentration_monitor.py`.

Signal stack health:

```text
OK=61
STALE=0
MISSING=0
ERROR=0
DISABLED=1
```

Strategy staleness alert:

```text
paper_challenger: zero_entries_since_activation_9_business_days
```

Readiness scorecard:

```text
overall_score=6.0
can_submit_orders=false
execution_enabled=false
Operational integrity=10/10
Autonomous safety=10/10
Risk controls=6/10
Entry quality=7/10
Exit quality=4/10
Counterfactual gate quality=0/10
Proven profitability=4/10
```

Profitability remains evidence-capped:

```text
closed=13
days=31
net_pnl=2312.0
expectancy=177.85
profit_factor=4.78
max_drawdown=-591.0
```

These are encouraging but too small for durable profitability claims.

## Verification

Focused options safety lane:

```powershell
python -m pytest agent\tests\test_iwm_options_confidence_gate.py `
  agent\tests\test_options_state_integrity.py `
  agent\tests\test_options_position_reconciler.py `
  agent\tests\test_options_lifecycle_pnl.py `
  agent\tests\test_options_shadow_twin.py `
  agent\tests\test_self_learning_edge_loop.py `
  agent\tests\test_execution_gate_audit.py `
  agent\tests\test_garch_volatility_risk.py `
  test_iwm_options_execution_guard.py -q
```

Result:

```text
101 passed, 1 warning
```

Compile check:

```powershell
python -m py_compile strategies\iwm_options_bot.py strategies\flip_bot.py `
  scripts\options_position_reconciler.py scripts\options_shadow_twin.py `
  scripts\market_schedule_alignment.py scripts\execution_gate_audit.py `
  scripts\signal_stack_health_report.py scripts\elite_bot_readiness_scorecard.py
```

Result: passed.

Broader safety pack was run and is not clean:

```text
282 passed, 1 warning, 3 failed
```

The 3 failures are pre-existing `flip_bot` entry-limit rounding expectation mismatches:

- expected `0.72`, actual `0.73`
- expected `1.30`, actual `1.31`

Do not represent the full broader suite as green until those are resolved or formally classified.

Full repo suite was also not clean before this handoff. Previously observed:

```text
4276 passed, 4 skipped, 13 failed
```

Failures were outside the options changes: `flip_bot`, Futu/Mootdx, Polymarket wallet tracker, and shadow volume coverage.

## Worktree Notes

Scoped options files are clean and committed after the six commits.

The repo still has unrelated dirty generated logs, research artifacts, handoff files, and one unrelated tracked strategy file:

- `strategies/polymarket_wallet_tracker.py`
- many `data/*.jsonl`
- several untracked July 25 research/handoff files
- submodule dirt in `tools/tradingview-mcp`

Preserve those unless Kenny explicitly asks to clean them.

`agent/.env` is intentionally ignored. Codex updated the local runtime config but did not commit it because `.env` is ignored.

## Next Claude Code Actions

1. Wait for or inspect `IWM-Residual-Clearance` after July 29, 2026 8:32 AM Central.
2. Re-run `python scripts\options_position_reconciler.py --print`.
3. Require `entries_allowed=True` before letting `IWM-Bot-Entry` create any new options entry.
4. Verify `IWM-Bot-Entry` respects the new ET entry windows and the IV/RV gate.
5. Watch `data/options_shadow_twin_log.jsonl` after the first eligible or blocked candidate.
6. Diagnose the 3 `flip_bot` rounding test failures separately.
7. Do not force trades, do not enable live execution, and do not loosen thresholds to create activity.

## Paste-Ready Prompt For Claude Code

Read `CODEx_CLAUDE_COLLAB/CODEX_TO_CLAUDE_HANDOFF_2026-07-29_OPTIONS_EDGE_OPERATIONS.md` first. Operate read-only until the IWM residual is reconciled. Confirm scheduled-task results, run the options reconciler, verify context freshness, and preserve unrelated dirty files. Keep `ALPACA_PAPER=true`. Do not force a trade or bypass blockers. If a reproducible defect appears, fix it with focused tests and commit only the scoped files. Do not claim proven profitability from the current small sample.
