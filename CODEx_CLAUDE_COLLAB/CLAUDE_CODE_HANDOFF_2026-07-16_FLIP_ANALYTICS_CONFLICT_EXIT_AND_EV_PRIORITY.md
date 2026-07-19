# Claude Code Handoff: Flip Analytics Repair, Conflict Exit, and EV Priority

Date: 2026-07-16

## Why This Was Urgent

The current SPY loss reached `best_pnl_pct=+12.61%` and exited at `-37.83%`. The learning pipeline incorrectly labeled it as a winner that faded and told the bot to tighten winner exits. Two reports also disagreed on capture efficiency (`0.0` versus `-3.0`). That was a harmful analytics defect, not an execution defect.

## Repair Delivered

### One canonical exit taxonomy

New shared utility: `scripts/flip_exit_taxonomy.py`.

It is now used by:

- `scripts/flip_exit_quality_report.py`
- `scripts/closed_trade_postmortem.py`
- `scripts/flip_bot_learning_report.py`
- `scripts/loop_closure_report.py`

Rules:

- Capture efficiency and giveback exist only when `exit_return_pct > 0` and observed MFE is positive.
- A losing exit can never produce a winner-capture lesson.
- A loss that briefly went green records `favorable_excursion_surrendered_pct` separately.
- A stop after favorable excursion is `stop_loss_after_favorable_excursion`.
- Loop closure recomputes canonical quality from the trade and cannot trust stale contradictory postmortem values.

The actual SPY trade now reports:

- classification: `stop_loss_after_favorable_excursion`
- capture efficiency: `null`
- giveback: `null`
- favorable excursion surrendered: `50.44`
- lesson: investigate entry timing, reversal detection, and first post-entry directional conflict; explicitly not winner-capture evidence
- loop state: `entry_filter_review`

All current JSON reports were regenerated. No current report contains the stale `Winner faded too much before exit` lesson. Historical append-only logs were not rewritten.

### Weakening-signal exit experiment

`strategies/flip_bot.py` now attaches a point-in-time market-force snapshot to every new forward shadow entry and mark.

Snapshot qualification requires:

- source report declares `execution_enabled=false`
- timestamp is not from the future
- age is no more than 30 minutes

`scripts/flip_shadow_pnl_evaluator.py` now records a counterfactual exit at the first qualified post-entry directional conflict:

- CALL conflicts with `bearish_confirmation`
- PUT conflicts with `bullish_confirmation`
- entry-row classifications never count; conflict must occur after fill
- entry ask / exit bid is used when available, otherwise midpoint is explicitly non-promotion-grade
- result is compared with the existing baseline simulated exit

Authority is `shadow_only`. Review requires 10 completed conflict observations. Current honest state is `0/10`; legacy rows are not reconstructed.

### Time-bucket research ranking

`scripts/flip_shadow_time_bucket_report.py` no longer calls three samples actionable.

- 10 completed lifecycles: eligible for shadow ranking only
- 30 completed lifecycles: gate-review sample floor, still no automatic gate
- `live_gate_eligible=false` for every bucket
- `time_gate_authority=none`

Current cumulative ranking after regeneration:

1. 12:00 ET: `n=19`, win rate `63.2%`, expectancy `+24.21%`
2. 11:30 ET: `n=18`, win rate `55.6%`, expectancy `+13.52%`
3. 13:30 ET: `n=28`, win rate `35.7%`, expectancy `-0.22%`

### Paper challenger order

Both Flip runners now set:

`FLIP_PAPER_CHALLENGER_SYMBOLS=RIVN,AAPL,NVDA,QQQ`

IWM was removed from active paper-challenger scanning because cumulative shadow EV is negative. QQQ remains fourth. Existing one-contract paper-only authorization remains unchanged. Outside paper mode these challengers still fail closed.

## Verification

- Focused tests: `72 passed`
- Direct CLI imports and report generation: passed
- Python compilation: passed
- Execution gate audit: `passed=true`, `issue_count=0`, `execution_enabled=false`
- Risk proof: `passed=true`, 4/4 cases, `can_submit_orders=false`
- `git diff --check`: clean except normal Windows LF/CRLF notices

## Claude Review Queue

1. Review the canonical taxonomy and ensure any future analytics import it instead of recreating capture formulas.
2. Verify tomorrow's new schema-v3 marks contain `market_force_snapshot_status=current` and point-in-time timestamps.
3. After 10 completed conflict observations, compare conflict exit return against baseline by direction, symbol, and time bucket. Do not promote before then.
4. Keep 12:00 as a shadow ranking preference until at least 30 completions and human review; do not create a live time gate.
5. Re-evaluate challenger order from cumulative cost-adjusted EV, not single-trade screenshots.

## Explicit Non-Changes

- No real-money activation.
- No live exit rule change.
- No stop, target, ratchet, sizing, liquidity, reconciliation, or kill-switch change.
- No directional-conflict auto-close.
- No time-of-day execution veto.

