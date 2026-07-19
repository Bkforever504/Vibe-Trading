# Claude Handoff: Flip Attribution, Quote Age, Exit Quality, Options P&L De-duplication

Date: 2026-07-13 America/Chicago (some runtime artifacts are 2026-07-14 UTC)
From: Codex
Owner: Kenny

## Paths

- Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
- Runtime: `C:\Users\kenne\.vibe-trading`
- Prior queue: `CODEx_CLAUDE_COLLAB\CODEX_HANDOFF_BOT_UPGRADES_2026-07-10.md`

The worktree remains intentionally very dirty with Kenny/Claude/Codex work. Preserve unrelated changes. Do not reset, clean, or rewrite files wholesale.

## Scope Completed

All four bounded tasks in `CODEX_HANDOFF_BOT_UPGRADES_2026-07-10.md` are complete. This work changed telemetry and read-only reporting only. No thresholds, gates, risk caps, live flags, order payloads, or kill-switch behavior changed. No orders were submitted.

## 1. Flip Decision Attribution

Changed:

- `strategies/flip_bot.py`
- `agent/tests/test_flip_decision_log.py`

Added append-only decision events at:

`C:\Users\kenne\.vibe-trading\logs\flip-decisions.jsonl`

Schema:

```json
{
  "ts": "UTC timestamp",
  "symbol": "SPY",
  "strategy": "bear_trend",
  "action": "skip|blocked|submitted",
  "reason": "one stable primary reason",
  "paper": true,
  "details": {}
}
```

Instrumented reasons include:

- `market_closed`
- `max_open_positions`
- `entry_cutoff`
- `stale_session`
- `insufficient_bars`
- `intraday_fetch_failed`
- `insufficient_intraday_data`
- `score_below_minimum`
- `breadth_not_confirmed`
- `vix_term_structure_direction_block`
- `no_catalyst_confirmation`
- `atm_option_unavailable`
- `budget_insufficient`
- `budget_or_spread_unavailable`
- `symbol_not_promoted`
- `same_day_reentry`
- `shadow_consensus_block`
- `execution_guard_block`
- `order_submission_failed`
- `candidate_passed_all_filters`

Attribution is emitted at high-level strategy boundaries so one missing underlying feed does not inflate one skipped setup into multiple events. Existing logs and returns are behavior-identical.

The runtime JSONL does not exist yet because this was implemented after market close. Verify the first scheduled entry cycle writes it before consuming it in analytics.

## 2. Quote-age Capture

Changed:

- `strategies/flip_bot.py`
- `agent/tests/test_flip_decision_log.py`

The Alpaca quote already fetched by `_option_mid()` now records selection telemetry keyed by OCC symbol:

- `selection_bid`
- `selection_ask`
- `quote_timestamp`
- `quote_age_seconds`

Direct 0DTE, bear-trend, and bull-trend setup records carry these fields into `entry_quality`. Missing or malformed quote timestamps produce `quote_age_seconds: null`; no timestamp is guessed and no new gate was added.

Debit-spread candidates retain null quote-age fields unless their selected long option was directly quoted. Do not turn this telemetry into a freshness gate without forward evidence, tests, dual review, and Kenny approval.

## 3. Flip Exit-quality Report

Added:

- `scripts/flip_exit_quality_report.py`
- `agent/tests/test_flip_exit_quality_report.py`

Runtime report:

`C:\Users\kenne\.vibe-trading\reports\flip-exit-quality.json`

The report is explicitly read-only (`execution_enabled=false`, `can_submit_orders=false`) and computes only when all required telemetry exists:

- hold minutes
- realized return percent
- MFE and MAE
- realized/MFE capture efficiency
- giveback percent
- stop return percent
- MAE distance from stop

Real runtime baseline:

- 11 historical closed Flip trades
- 0 complete under the new telemetry contract
- 11 `insufficient_data`

This is expected and correct. Legacy records lack combinations of `entry_at`, `exit_at`, `best_pnl_pct`, and `worst_pnl_pct`. The report never estimates these fields. New closes will build the forward sample.

Command:

```powershell
python scripts\flip_exit_quality_report.py --print
```

Do not change exits from this report until it has enough forward/OOS evidence under `rules\signal_promotion_rules.md`.

## 4. Options Reporting P&L De-duplication

Added/changed:

- `scripts/options_reporting.py`
- `scripts/closed_trade_postmortem.py`
- `scripts/loop_closure_report.py`
- `scripts/generate_dashboard.py`
- `agent/tests/test_options_reporting.py`
- `agent/tests/test_closed_trade_postmortem.py`

`dedupe_options_trade_records()` collapses duplicate **closed** records sharing a non-empty opening `order_id`, preferring the lifecycle with the most populated fields. Deterministic ties prefer the original non-`recovered-` record.

Safety properties:

- Does not mutate `options-trades.json`.
- Never collapses open records.
- Never collapses records without an `order_id`.
- Only affects read-only postmortem, loop-closure P&L, and dashboard reporting.

Real runtime result:

- Raw options records: 12
- Reporting records: 10
- Duplicate closed records removed from reporting: 2
- Raw closed count: 10
- Canonical reporting closed count: 8

The two known recovered/original duplicates remain intact in durable state.

## Verification

Expanded named safety/report suite:

```powershell
python -m pytest agent\tests\test_flip_bot_safety.py agent\tests\test_flip_entry_quality.py agent\tests\test_flip_bear_trend.py agent\tests\test_flip_shadow_pnl_evaluator.py agent\tests\test_flip_bot_learning_report.py agent\tests\test_daily_edge_orchestrator.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_signal_stack_grades.py agent\tests\test_generate_dashboard.py agent\tests\test_execution_gate_audit.py agent\tests\test_shadow_consensus_gate.py agent\tests\test_shadow_consensus_exit_advice.py agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_options_state_integrity.py agent\tests\test_options_position_reconciler.py agent\tests\test_bot_status_snapshot.py agent\tests\test_signal_stack_health_report.py agent\tests\test_daily_eod_summary.py agent\tests\test_nightly_research_loop.py agent\tests\test_market_schedule_alignment.py agent\tests\test_flip_decision_log.py agent\tests\test_flip_exit_quality_report.py agent\tests\test_options_reporting.py agent\tests\test_closed_trade_postmortem.py agent\tests\test_loop_closure_report.py -q -p no:cacheprovider
```

Result: `158 passed`, one dependency deprecation warning.

Additional verification:

- `python -m compileall -q strategies scripts`: clean.
- Position reconciler: zero unexplained residual; known P277 netting only; entries remain fail-closed.
- Execution gate audit: 87 signals, zero issues.
- Signal stack health: 45 OK, 0 stale, 0 missing, 0 error.
- Schedule alignment: 43/43, zero issues. Two known extra-start-time warnings for Flip/IWM monitors remain.
- Dashboard regenerated successfully at `C:\Users\kenne\.vibe-trading\dashboard.html`.
- `git diff --check` clean for tracked touched files; only line-ending notices.

## Claude Review Requests

1. Review reason-code placement for duplicate inflation after the first actual scheduled Flip entry cycle.
2. Confirm Alpaca snapshot timestamp key `latestQuote.t` remains populated and UTC parseable in the host feed.
3. Let new telemetry accumulate; do not backfill or infer legacy MFE/MAE timestamps.
4. Review de-duplication completeness ordering against the two real recovered/original pairs. Keep state immutable.
5. Do not schedule or promote `flip_exit_quality_report` as an execution input. It is evidence only.

## Non-negotiable Controls

- Keep `STOP_MULT=0.70`, daily realized-loss guard, `MAX_CONTRACTS=5`, and 2% risk cap.
- Keep reconciliation, two-observation flat confirmation, quote completeness, execution guard, CPI/news, and kill-switch behavior intact.
- Paper only. Do not enable live flags.
- Social/news/shadow reports cannot submit orders.
- No threshold changes from this small or incomplete sample.

## Post-handoff Correction: Pytest Runtime Isolation

The first `flip-decisions.jsonl` was inspected and all 24 rows were proven pytest artifacts, not a scheduler cycle. Evidence included repeated post-close test sequences and stub order IDs `order` and `spread-order`.

Fixes:

- `strategies/flip_bot.py` now honors `FLIP_DECISION_LOG_FILE` when binding the decision path.
- Repository-root `conftest.py` sets that environment variable before test-module collection to a process-specific temp path. This covers both `agent/tests` and root test files, including top-level imports.
- `agent/tests/test_flip_decision_log.py` asserts pytest never targets Kenny's real runtime log.
- Root `test_bull_trend_spread.py` fixtures were made deterministic and aligned with the current three-of-three bull breadth rule.
- `agent/tests/test_flip_bot_learning_report.py` now uses a temporary grades report instead of reading mutable runtime promotion state.

The contaminated log was archived intact at:

`C:\Users\kenne\.vibe-trading\archive\flip-decisions.test-artifacts-20260714T011053Z.jsonl`

Post-fix proof:

- Archive contains all 24 original rows.
- `C:\Users\kenne\.vibe-trading\logs\flip-decisions.jsonl` remains absent after the full regression run.
- Expanded suite: `168 passed`, one dependency deprecation warning.
- Compile clean; execution audit still 87 signals / zero issues.

The next newly created runtime decision log can now be treated as genuine scheduled/process telemetry, subject to checking its timestamps and broker order IDs.
