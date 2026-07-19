# Codex Handoff - Bot Upgrade Program Continuation

Date: 2026-07-10
From: Claude Fable 5 (with Kenny's host verification)
To: Codex
Owner: Kenny
Workspace: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Runtime state: `C:\Users\kenne\.vibe-trading`

## Mission

Continue the Fable 5 upgrade program (see
`CLAUDE_FABLE5_HANDOFF_MAJOR_BOT_UPGRADES_2026-07-10.md` for the full phase
plan). Phase 0 is complete and host-verified. Phase 1 Part 1 (flip entry
telemetry) is complete. Your work starts at Phase 1 Part 2.

"Major upgrades" means stronger evidence, cleaner state, fewer false
signals, better execution discipline, and faster learning - never more
trades, looser risk, or lower thresholds.

## Read First (in order)

1. `CLAUDE.md`
2. `STATUS.md`
3. `CODEx_CLAUDE_COLLAB\CLAUDE_FABLE5_HANDOFF_MAJOR_BOT_UPGRADES_2026-07-10.md` (master plan, hard safety rules)
4. `CODEx_CLAUDE_COLLAB\CLAUDE_FABLE5_PHASE0_POSITION_INTEGRITY_HANDOFF_2026-07-10.md`
5. `CODEx_CLAUDE_COLLAB\CLAUDE_FABLE5_PHASE1_FLIP_ENTRY_QUALITY_HANDOFF_2026-07-10.md`
6. `rules\signal_promotion_rules.md`

The worktree is intentionally dirty with Kenny/Claude/Codex work. Preserve
existing changes. Never reset, revert, or rewrite files wholesale.

## Current Verified Baseline (2026-07-10, Windows host)

- Full master + Phase 0 suites: 117+ passed on host; sandbox runs since
  then add flip telemetry tests (see verification block below).
- Compile clean; execution audit 87 signals / 0 issues; stack health 44 OK;
  schedule alignment 42/42; dashboard regenerates.
- Live Alpaca reconciliation: exact signed-book balance, zero unexplained
  residuals.
- No live flags, kill-switch, or risk-cap changes anywhere.

### Phase 0 (complete, host-verified)

- Root cause of the 2026-07-07 incident identified and fixed: a single
  transient empty positions response mass-closed all groups; new IWM condor
  then opened sharing the P277 strike (nets to zero at broker).
- `strategies/options_state.py`: signed-book reconciliation engine
  (netting-aware, fail-closed, read-only), group state machine,
  `atomic_save_json` (lock + temp + fsync + replace), and `quote_mark`
  (quote-based group marking with per-leg close sides).
- `strategies/iwm_options_bot.py`: reconciliation runs every monitor cycle
  (`POSITION INTEGRITY:` log lines, fail-closed); flat confirmation needs
  two observations >= `OPTIONS_FLAT_CONFIRM_MIN_SECONDS` (600s) apart;
  `leg_details` recorded on new trades; netted-leg groups are now managed
  via fresh quote marks (`_quote_mark_is_fresh`, 300s freshness) and closed
  with grouped limit orders derived from `quote_mark` close legs -
  incomplete quote coverage refuses the exit (fail closed).
- `scripts/options_position_reconciler.py`: read-only reconciler; loads
  `agent\.env` automatically (never overriding shell env); prefers live
  read-only Alpaca positions, falls back to portfolio-concentration.json
  with staleness labeling; emits approval-gated repair plans. Report:
  `~\.vibe-trading\reports\options-position-reconciliation.json`.
- Approved repair applied: old condor `1733badd` restored to tracking
  (`needs_manual_review: true`, `wrongly_closed_at` preserved). Backup at
  `~\.vibe-trading\options-trades.backup-2026-07-10-pre-repair.json`.

### Phase 1 Part 1 (complete)

- `strategies/flip_bot.py`: every new trade records `entry_at` (UTC) and
  `entry_quality` {entry_minute_et, entry_price_est, filled_price,
  fill_price_source (broker_fill|estimate_fallback), slippage_per_contract,
  slippage_pct, spread_cents_at_signal, orb_direction, signal_snapshot
  {score, close, vwap, ema50, vwap_distance_pct, reasons}}.
- MAE tracking (`worst_pnl_pct`) alongside MFE; both exit paths stamp
  `exit_at` via shared `_stamp_exit`; `_save` is atomic/locked; `_get`
  mutable default fixed.
- Also in tree (verify, do not weaken): flip daily realized-loss guard
  (`_today_realized_loss_pct`, closed-trade P&L only) and STOP_MULT 0.70
  (-30% stop). Regression tests exist for both.
- NO decision logic changed by telemetry work: entries, exits, thresholds
  and confidence gates are behavior-identical.

## Known Issues / Carried Items

1. Two IWM condors share the netted P277 leg until one exits (expiry
   2026-08-07). Quote-mark management now covers them, but treat their
   first live-market exit as a watched event: confirm the grouped close
   fills and durable state transitions correctly.
2. Duplicate recovered-vs-original lifecycles in options-trades.json
   (`recovered-eb43c916...` vs `2628a70c...`, `recovered-11f62309...` vs
   `2c8b2010...`): P&L reports keyed per trade double-count. Fix belongs in
   the P&L/reporting layer keyed by order_id; do not rewrite trade history.
3. Options entries remain gated by reconciliation; that is correct while
   the netted overlap exists.

## Your Work Queue (bounded, in order)

### Task 1 (start here): Flip skip attribution - `flip-decisions.jsonl`

Phase 1 requires every skipped SPY setup to have ONE primary reason.
The options bot already has the pattern: `_decision()` in
`strategies/iwm_options_bot.py` writing `options-decisions.jsonl`.

- Add an equivalent `_decision()` to `strategies/flip_bot.py` writing
  `~\.vibe-trading\logs\flip-decisions.jsonl` (append-only JSONL; include
  UTC timestamp, symbol, strategy, action=skip|submitted|blocked, one
  primary reason code, and a details dict).
- Instrument every skip/block path: entry cutoff (past 2pm), insufficient
  bars, stale session, breadth < 2/3, score below minimum, no ATM option,
  budget/spread failures, same-day re-entry block, shadow consensus block,
  execution guard block, VIX term-structure direction block.
- One primary reason per event. No new gates, no changed gates - only
  attribution of existing decisions.
- Tests: reason-code stability, one-event-per-skip (no duplicate
  inflation), and JSONL schema.

### Task 2: Quote-age capture at flip entry

`_atm_option` selects the contract but records no quote timestamp. Capture
quote age (and bid/ask at selection time) into `entry_quality`. Read-only
data addition; if the quote payload lacks a timestamp, record
`quote_age_seconds: null` rather than guessing. Extend
`agent\tests\test_flip_entry_quality.py`.

### Task 3: Phase 2 exit-evidence groundwork (analytics only)

With `entry_at`/`exit_at`/MFE/MAE now accumulating, build a read-only
report `scripts/flip_exit_quality_report.py` (pattern-match existing
report scripts): per closed trade compute hold minutes, capture efficiency
(realized / MFE), giveback, MAE-vs-stop distance. Emit
`~\.vibe-trading\reports\flip-exit-quality.json` with
`execution_enabled: false`. NO production threshold changes - evidence
only. Trades without telemetry are listed as `insufficient_data`, not
estimated.

### Task 4 (only if 1-3 are done and green): Options P&L de-duplication

Reporting-layer fix for carried item 2: key closed-trade P&L by
`order_id`, preferring the record with the most complete lifecycle.
Read-only report change; never edit options-trades.json history.

Stop after Task 4 (or earlier if any test fails or scope grows). Leave a
dated handoff in `CODEx_CLAUDE_COLLAB`.

## Hard Safety Rules (unchanged, non-negotiable)

- Never enable live trading; never set `LIVE_EXECUTION_ENABLED` or
  `FLIP_LIVE_EXECUTION_ENABLED` true.
- Never raise `MAX_CONTRACTS` above 5 or per-trade risk above 2%.
- Never delete or mock kill-switch/manual-reset files.
- Never loosen the execution guard, confidence gates, or entry filters to
  create more trades.
- Never weaken: two-observation + time-separated flat confirmation;
  reconciliation fail-closed behavior; quote-mark completeness check on
  grouped closes; flip daily realized-loss guard; STOP_MULT 0.70.
- Never auto-close or rewrite the IWM condor state from inference.
- Never wire social/X/prediction-market/copy-trader context to orders.
- Never promote a symbol/scanner without `rules\signal_promotion_rules.md`.
- New reports default `execution_enabled: false`, `can_submit_orders: false`.
- Do not put secrets in reports or handoffs.

## Verification (run before and after your changes)

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

python -m pytest agent\tests\test_flip_bot_safety.py agent\tests\test_flip_entry_quality.py agent\tests\test_flip_bear_trend.py agent\tests\test_flip_shadow_pnl_evaluator.py agent\tests\test_flip_bot_learning_report.py agent\tests\test_daily_edge_orchestrator.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_signal_stack_grades.py agent\tests\test_generate_dashboard.py agent\tests\test_execution_gate_audit.py agent\tests\test_shadow_consensus_gate.py agent\tests\test_shadow_consensus_exit_advice.py agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_options_state_integrity.py agent\tests\test_options_position_reconciler.py agent\tests\test_bot_status_snapshot.py agent\tests\test_signal_stack_health_report.py agent\tests\test_daily_eod_summary.py agent\tests\test_nightly_research_loop.py agent\tests\test_market_schedule_alignment.py -q -p no:cacheprovider

python -m compileall -q strategies scripts
python scripts\options_position_reconciler.py --print
python scripts\execution_gate_audit.py --print
python scripts\signal_stack_health_report.py
python scripts\market_schedule_alignment.py --print
python scripts\generate_dashboard.py
```

Expected: all tests pass; compile clean; reconciler explains the P277
netting with zero unexplained residual; audit zero issues; no live-flag or
kill-switch diffs; every new behavior has a focused regression test.

## Deliverable Per Task

- Findings ordered by severity; exact files changed; tests/commands run;
  before/after behavior; remaining risks; next single highest-value task;
  dated handoff in `CODEx_CLAUDE_COLLAB`.
