# Codex Handoff: Liquidity Sweep Proxy

Date: 2026-08-11
Orders submitted: 0
Execution changes: none

## What changed

- Rebuilt `scripts/liquidity_sweep_scanner.py` as a point-in-time failed-breakout
  event study, not an institutional-intent detector.
- Removed the unvalidated hard veto from `strategies/spy_iron_condor.py`.
- Added research-only sweep context to the iron-condor and 0DTE PM spread
  setup/evidence payloads.
- Added stable event IDs, idempotent ledger upserts, actual event/availability
  timestamps, shifted volume baselines, PDH/PDL and ONH/ONL levels, 5/15/30/60
  minute returns, and 60-minute MFE/MAE.
- Added a limited scheduled scanner at 08:43, 09:35, and 10:40 CT and brought
  all triggers under schedule governance. Strategy entry reads a fresh cache,
  so optional telemetry adds no entry-path network request.
- Added focused detector, lookahead, idempotency, authority, integration, and
  schedule tests.

## Safety boundary

`research_context()` always reports:

- `promotion_status: research_only`
- `execution_authority: false`
- `can_submit_orders: false`
- `veto: false`

Do not turn this into a gate from underlying hit rate. First require 100 events
across 60 sessions, then run a strategy-specific walk-forward option backtest
using executable quotes and costs. A future MBO study may test order-flow
mechanics, but OHLCV data must remain labeled as a proxy.

## Verification

- Focused suite: 28 passed
- Live-data smoke probe: completed, zero events at the off-session check
- Full repository suite: 4,600 passed, 4 skipped
- Scheduler task: registered, limited privilege, Ready
- Schedule governance: 76/76 aligned, 0 issues, 0 warnings

## Next useful work

1. Confirm the first two weekday runs populate and then refresh the same event
   IDs without duplication.
2. Review the new liquidity-sweep cohorts in the options edge attribution
   report after resolved shadow outcomes arrive.
3. After the sample threshold, preregister debit-spread, put-credit-spread, and
   condor hypotheses separately and test each net of executable friction.
4. If Databento MBO is funded, add queue depletion, aggressive flow, and
   markout features as a separate challenger. Do not relabel the OHLCV proxy.
