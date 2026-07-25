# Claude P0 Report: Canonical Lifecycle Adapter and Contamination Audit

Date: 2026-07-24
Handoff: `CLAUDE_CODE_HANDOFF_THREE_BOT_UPGRADE_2026-07-24.md`
Scope: P0 only, plus the operational-truth precondition. No strategy logic,
risk, sizing, or execution behavior was changed.

## Operational Precondition (completed first, commit `b8f8b8c`)

- Stale output root cause: `\VibeTrade\PolymarketWeatherBot` is deliberately
  Disabled in Task Scheduler (last run 7/15, exit 0). The health report had no
  disabled category and graded it stale forever. Fixed with a distinct
  `disabled` health class and summary count; it stays visible.
- Schedule-alignment issue root cause: any task status other than "Ready" was
  an issue, so the alignment task failed by observing itself "Running" at its
  own 19:58 run (33 of 41 historical `task_not_ready` events were exactly
  this). Fixed: "Running" within a 30-minute grace window of the task's last
  run time is healthy; beyond it becomes a new `task_running_too_long` issue,
  so genuinely stuck tasks still surface. Disabled/other statuses still fail.
- Verified live: schedule alignment now `passed=True, 55/55 aligned, 0 issues`;
  health shows `MISSING=0 ERROR=0 DISABLED=1`.
- Honest note: 2026-07-24 shows real missed-run staleness because the machine
  was off during market hours (the scheduled 15:35 health run never fired and
  catch-up runs died with exit 0xC000013A). Not masked; clears on the next
  full trading day.

## P0 Deliverables

New files:

- `scripts/lifecycle_normalizer.py` — versioned (`1.0.0`), read-only canonical
  adapter. Emits normalized views with `bot_family`, `strategy_family`,
  `instrument_type`, `position_effect`, `direction` (+ `direction_basis`),
  `outcome_status`, family-correct P&L/risk semantics, provenance, and
  explicit quarantine with `unknown_reasons`. Cross-family fields are
  `not_applicable`. `assert_rule_compatible` fails closed with
  `FamilyRuleViolation` when one family's rules touch another family's view.
- `scripts/lifecycle_contamination_audit.py` — read-only audit comparing
  legacy postmortem/learning labels against the canonical adapter. Writes
  `~/.vibe-trading/reports/lifecycle-contamination-audit.json`. Manual CLI,
  not a scheduled scanner.
- `agent/tests/test_lifecycle_normalizer.py` — 10 tests.

Family semantics implemented:

- `flip_directional_debit`: direction from option right (PUT=bearish,
  CALL=bullish); strategy/right conflicts (e.g. `bull_trend` + PUT) are
  quarantined, not guessed. P&L = (exit-entry) x 100 x contracts; risk basis
  is debit paid.
- `options_defined_risk_credit`: direction from structure only — a bull put
  credit spread is bullish even though its legs are puts; leg `right` is
  `not_applicable` for direction. P&L = (credit - closing debit) x 100 x qty;
  risk = max_risk x qty; return measured on max risk. `recovered_mleg` is
  quarantined as `unclassified_credit_structure`.
- `topstep_mes_futures`: direction from side; P&L = signed points x $5 point
  value x contracts - fees. Adapter ready; no closed MES trades exist yet.
- Direction-aware trend alignment returns `unknown` with
  `missing_bearish_feature_keys`/`missing_bullish_feature_keys` instead of
  silently grading a put "unconfirmed" against bullish-only keys.

## Contamination Audit: Live Counts (2026-07-24)

| Check | Count |
|---|---|
| Flip records normalized | 13 (0 direction mismatches, 0 quarantined) |
| Options records normalized | 16 |
| Options quarantined | 12 |
| — `closed_without_resolvable_pnl` | 12 |
| — `unclassified_credit_structure:recovered_mleg` | 3 |
| — `missing_max_risk` | 3 |
| — `missing_or_nonpositive_net_credit` | 1 |
| Options credit-rule misapplication (no positive credit) | 1 |
| Shadow rows graded for trend labels | 4,855 (0 missing-key unknowns; current schema carries both key sets) |
| Mistake-ledger rows | 181 (only 34 carry context) |
| — context `expected_move_bucket=unknown` | 21 |
| — context `entry_pattern=unknown` | 9 |
| — context `retest_status=unknown` | 9 |
| — context `trend_alignment=unconfirmed` (possibly missing keys) | 34 |

Most important finding: 12 of 13 closed options positions have no resolvable
P&L under honest credit semantics. The legacy path regex-estimates P&L from
the closing-reason text ("% of credit"), which is not fill evidence. This
confirms the handoff's options evidence gap and means options challenger
support counts built from those labels are not trustworthy until lifecycle
P&L capture (P2) lands.

Ledger rows are immutable and were not rewritten. Rows with unknown/ambiguous
context must be excluded from challenger support until re-derived through the
normalizer (next step, pending review).

## Learning-Report Consumption Status

Per handoff P0.5, current declarations:

- `scripts/closed_trade_postmortem.py`, `scripts/accelerated_bot_learning_report.py`,
  `scripts/self_learning_edge_loop.py` do NOT yet consume normalized views.
  Rewiring them changes challenger-support counts and deserves its own
  reviewed change after this P0 report is accepted.

## Verification

- `python -m pytest agent/tests/test_lifecycle_normalizer.py -q` → 10 passed
- `python -m pytest agent/tests/test_signal_stack_health_report.py
  agent/tests/test_market_schedule_alignment.py -q` → 16 passed
- Downstream health consumers (eod summary, bot status, dashboard, nightly,
  scorecard suites) → 26 passed
- `python scripts/execution_gate_audit.py` → exit 0
- `python scripts/market_schedule_alignment.py --print` → passed, 0 issues

## Boundaries Respected

No live trading, no order paths, no risk/stop/target changes, no MES task
enablement, no historical log rewrites, no automatic promotion, no spending.
