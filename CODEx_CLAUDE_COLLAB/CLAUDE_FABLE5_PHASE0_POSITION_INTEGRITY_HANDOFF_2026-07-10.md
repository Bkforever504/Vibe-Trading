# Claude Fable 5 - Phase 0 Handoff: Position And Order Integrity

Date: 2026-07-10
Author: Claude Fable 5
Phase: 0 (Position And Order Integrity) - COMPLETE
Prior handoff: CLAUDE_FABLE5_HANDOFF_MAJOR_BOT_UPGRADES_2026-07-10.md

## Findings, Ordered By Severity

### F1 (Critical, root cause identified): 2026-07-07 09:45:03 ET mass flat-close

Log evidence (`~\.vibe-trading\logs\options-bot.log` line 1088):

```
2026-07-07 09:45:03  INFO  No open option positions remain; marked tracked groups closed
```

A single transient empty broker positions response at market open marked ALL
tracked open groups closed with no closing_reason: IWM Iron Condor `1733badd`,
AAPL Put Spread `2c8b2010`, and PLTR Put Spread `2628a70c` all carry
`closed_at: 2026-07-07T14:45:03Z`. Six seconds later (09:45:09) the bot,
believing IWM was flat, opened a new Iron Condor `d72ded80`.

### F2 (Critical, fully explained): the current broker/state mismatch is strike netting

The old condor `1733badd` is LONG IWM260807P00277000 (+2). The new condor
`d72ded80` is SHORT the same contract (-2). At the broker they net to zero.
Signed-book reconciliation proves both condors are economically open:

```
old condor:  P279 -2, P277 +2, C317.5 -2, C320 +2
new condor:  P277 -2, P275 +2, C313 -2,  C315 +2
sum:         P279 -2, P275 +2, C313 -2, C315 +2, C317.5 -2, C320 +2, P277 0
broker:      exactly those 6 positions (P277 absent)   <- perfect match
unexplained residual: NONE
```

So: "missing leg" P277 = netted, and the 3 "untracked legs" belong to the
wrongly-closed `1733badd`. Nothing is lost or unknown.

### F3 (High): recovery was netting-blind

`_recover_untracked_mleg_groups` required an order's legs to be a subset of
untracked open broker symbols. Because P277 was netted to zero it was not in
the position list, the subset check failed, and the old condor was silently
skipped while PLTR/AAPL were recovered (12:00:04 log entries). It now logs a
partial-match warning pointing to the reconciler instead of staying silent.

### F4 (High): two-observation flat rule had no time separation

`_confirm_flat_trade` counted observations but two API glitches seconds apart
(retry burst, two monitor invocations) could still close durable state.

### F5 (Medium): durable state writes were not atomic or locked

`_save_trade_state` wrote options-trades.json in place. A crash mid-write
could truncate the file; overlapping bot/monitor runs could interleave writes.

### F6 (Medium): recovered PLTR/AAPL groups are duplicate lifecycles

`recovered-eb43c916...` and `recovered-11f62309...` duplicate the original
trades `2628a70c` / `2c8b2010` (same order ids). P&L accounting that sums per
trade will double-count these unless keyed by order_id. Not fixed in Phase 0
(analytics concern, not execution risk); flagged for the P&L/reporting phase.

## Exact Files Changed

1. `strategies/options_state.py` (NEW, stdlib-only, no broker imports)
   - Signed per-OCC-contract book building with per-leg side/qty inference
     (explicit `leg_details` preferred; structural inference labeled).
   - `reconcile(trades, broker_positions)`: quantity/direction-aware, detects
     netted symbols, closed-but-broker-open groups (exact bounded subset
     match, no guessing), duplicate active leg ownership, unexplained
     residuals. Fails closed. Never mutates inputs. Read-only.
   - Group state machine: tracked / partially_filled / open / exit_pending /
     closing / partially_closed / flat_pending_confirmation / closed /
     manual_review.
   - `atomic_save_json`: exclusive lock file + temp write + fsync +
     os.replace; stale-lock breaking; `StateLockTimeout`.

2. `strategies/iwm_options_bot.py`
   - `_save_trade_state` now uses `options_state.atomic_save_json`.
   - `_confirm_flat_trade` requires two flat observations separated by at
     least `OPTIONS_FLAT_CONFIRM_MIN_SECONDS` (default 600s) of real time;
     tracks `flat_first_observed_at`; unparseable timestamps restart the
     window. Would have prevented F1 outright.
   - `monitor_and_close` runs `options_state.reconcile` every cycle, logs
     each finding as `POSITION INTEGRITY: ...`, and fails closed (entries
     blocked) on any finding or on reconciliation error.
   - `_place_mleg` records durable `leg_details` (symbol/side/ratio_qty) on
     every new trade so future reconciliation never needs side inference.
   - `_recover_untracked_mleg_groups` warns on partial (netted) matches
     instead of silently skipping. Still never auto-recovers from inference.

3. `scripts/options_position_reconciler.py` (NEW, read-only)
   - Sources broker truth from live Alpaca read-only positions or falls back
     to portfolio-concentration.json (labeled with staleness).
   - Emits `~\.vibe-trading\reports\options-position-reconciliation.json`
     with `execution_enabled: false`, `can_submit_orders: false`, full
     reconciliation, and a proposed repair plan where every step carries
     `requires_kenny_approval: true`.
   - CLI: `--print`, `--no-live`, `--state-file`, `--positions-file`,
     `--output` (testable offline).

4. `agent/tests/test_options_state_integrity.py` (NEW, 13 tests)
   - Reproduces the real incident (exact symbols/quantities) and asserts the
     netted P277 is identified, `1733badd` is flagged closed-but-open, the
     active condor is manual_review, and unexplained residual is empty.
   - Atomic write validity, lock contention timeout, stale-lock breaking,
     8-thread concurrent write corruption test.
   - Flat-confirmation time-separation behavior.

5. `agent/tests/test_options_position_reconciler.py` (NEW, 4 tests)
   - Incident fixture end-to-end, clean-state no-op plan, fail-closed when no
     position source, atomic report write via main().

6. `agent/tests/test_iwm_options_confidence_gate.py` (UPDATED, 2 tests)
   - Flat-close test now collapses the time window explicitly via
     `FLAT_CONFIRM_MIN_SECONDS` monkeypatch (count behavior still covered).
   - Transient-flat test now uses realistic OCC symbols and signed qty so it
     passes the new quantity-aware integrity check honestly.

## Tests And Commands Run (sandboxed Linux, Python 3.10)

```
pytest: test_flip_bot_safety, test_flip_shadow_pnl_evaluator,
test_flip_bot_learning_report, test_daily_edge_orchestrator,
test_signal_stack_leaderboard, test_signal_stack_grades,
test_generate_dashboard, test_execution_gate_audit,
test_shadow_consensus_gate, test_shadow_consensus_exit_advice,
test_iwm_options_confidence_gate, test_bot_status_snapshot,
test_signal_stack_health_report, test_daily_eod_summary,
test_nightly_research_loop, test_market_schedule_alignment,
test_options_state_integrity, test_options_position_reconciler
-> 116 passed

python -m compileall strategies scripts -> passed

python scripts/options_position_reconciler.py --no-live --print
  (against real options-trades.json + real portfolio-concentration.json)
-> review_required, entries_allowed=False, unexplained_residual={},
   both condors classified manual_review, 2-step approval-gated plan.
   Report saved to ~\.vibe-trading\reports\options-position-reconciliation.json
```

Kenny should re-run the full required verification block from the prior
handoff on the Windows host (system Python) to confirm parity, especially
`execution_gate_audit`, `signal_stack_health_report`, and
`generate_dashboard`, which need host-local reports and scheduling context.

## Before / After Behavior

- Before: one empty positions response could close every tracked group
  (caused F1). After: closure needs two observations >= 10 minutes apart,
  and any reconciliation finding blocks entries.
- Before: "missing leg" and "untracked legs" were unexplained review noise.
  After: reconciler attributes both exactly (netting + wrongly-closed group)
  and produces an approval-gated plan; monitor logs name the cause.
- Before: state file writes could truncate/interleave. After: atomic,
  locked, fsynced.
- Before: new trades stored only leg symbols. After: durable side/qty per
  leg (`leg_details`).

## Current Runtime / Report State

- No broker orders placed. No positions changed. No durable trade state
  rewritten. Kill-switch and manual-reset files untouched. No live flags
  changed. New-entry blocking for options remains in force (and is now
  enforced by reconciliation, not just symbol comparison).
- New report present: `reports/options-position-reconciliation.json`
  (review_required, plan awaiting Kenny).
- STATUS.md untouched (still action_required, correctly).

## Repair Plan Awaiting Kenny's Approval

Recommended (Option A): edit options-trades.json to restore trade
`1733badd-f177-4b51-92fb-14e759280934` to `status: "open"` with
`needs_manual_review: true`, then let the monitor manage both condors.
After restoration the signed books reconcile exactly; the netted P277 needs
no order. Alternative (Option B): submit a grouped close of the old condor's
four legs (P279/P277/C317.5/C320) - note P277 must be BOUGHT back... no:
closing the old condor's long P277 means SELLING it, which at the broker
re-opens short exposure netted against the new condor's short. A grouped
close of the OLD condor plus keeping the new condor requires trading P277
and will interact with the new condor's short leg. Option A is materially
safer. Do not act without explicit approval either way.

## Remaining Risks And Evidence Gaps

- Per-group P&L for netted legs cannot come from per-symbol positions; after
  restoration the monitor's "missing leg -> manual review" path will (by
  design) keep flagging P277 until either one condor is closed or leg-level
  quote-based marking is added (candidate Phase 2/5 work).
- The duplicate recovered-vs-original lifecycles (F6) still overstate trade
  counts in analytics.
- `flat_observation_count` persisting requires `_save_trade_state` to be
  called on the all-flat path; existing code does this, verified by tests.
- Sandbox verification used Python 3.10/Linux; host is Windows. Path and
  locking code use stdlib `os.replace`/`O_EXCL`, which are correct on
  Windows, but Kenny's host run is the final word.

## Repair Executed (Kenny Approved Option A, 2026-07-10)

- Backup: `~\.vibe-trading\options-trades.backup-2026-07-10-pre-repair.json`
  (md5 977e2471d0d49eafa6ee8e755c56d043).
- Trade `1733badd` restored: `status: open`, `needs_manual_review: true`,
  `closed_at` moved to `wrongly_closed_at`, `repair_note` added. No broker
  orders placed.
- Post-repair reconciler run: closed_groups_still_open EMPTY, untracked
  legs EMPTY, unexplained_residual EMPTY. Remaining findings are only the
  known P277 netting overlap (both condors correctly manual_review,
  duplicate ownership of P277 flagged). Entries remain blocked -
  conservative and correct while two active groups share a netted leg.
- Updated report saved to `reports/options-position-reconciliation.json`.

### IMPORTANT operational caveat until the overlap resolves

The monitor skips exit logic for any group with a missing (netted) broker
leg, so AUTOMATED EXITS WILL NOT FIRE for either IWM condor while both are
open (this was already true for `d72ded80` since 2026-07-07 - not a
regression). Kenny should watch these two condors manually, or approve the
Phase 2 work item "quote-based marking for netted legs" to restore
automated management. Expiry for both: 2026-08-07.

## Next Single Highest-Value Task

Phase 1 (Flip Bot trade quality) per the master handoff, with one carried
P0-adjacent item: add quote-based P&L marking for netted option legs so the
two IWM condors regain automated exit management (Phase 2/5 scope, may be
pulled forward with Kenny's approval).

## Windows Host Verification (Codex, 2026-07-10)

Verified on Kenny's Windows host with system Python 3.12:

- Master handoff suite: 97 passed.
- Phase 0 integrity suite after the host fix below: 20 passed.
- Combined verified tests: 117 passed; only a third-party
  `websockets.legacy` deprecation warning remains.
- `python -m compileall -q strategies scripts`: passed.
- Execution gate audit: passed, 87 signals, 0 issues, 1 expected read-only
  broker-client warning.
- Signal stack health: 44 OK, 0 stale, 0 missing, 0 error.
- Market schedule alignment: 42/42 aligned, 0 issues, 2 known extra-start
  warnings for the Flip and IWM monitor tasks.
- Dashboard regenerated at `~\.vibe-trading\dashboard.html`.
- Daily Edge remained read-only with `execution_enabled: false` and
  `can_submit_orders: false`; SPY remains the only Flip execution symbol.
- Live Alpaca reconciliation used `alpaca_live_read_only` with
  `stale_seconds: 0`: no closed group still open, no unexplained residual,
  and exact signed-book balance. Review-required status is solely the known
  netted P277 duplicate ownership; entries remain blocked.
- No orders were placed, no live flags were enabled, and the portfolio kill
  switch remains active.

Host fix: `scripts/options_position_reconciler.py` now loads `agent\.env`
without overriding parent-shell variables. Previously, the documented plain
CLI silently fell back to the prior concentration report unless credentials
were manually injected into the shell. A regression test covers this path.
