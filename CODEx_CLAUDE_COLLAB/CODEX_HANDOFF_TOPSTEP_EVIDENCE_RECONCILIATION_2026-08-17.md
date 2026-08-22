# Claude Code Handoff: Topstep MES Evidence and Reconciliation

Date: 2026-08-17

## Current Honest State

- Execution remains disabled.
- No Topstep or ProjectX orders were submitted.
- TopstepX credentials and local-device confirmation are absent from `agent/.env`.
- The market recorder is blocked and no practice journal or broker-confirmed round trip exists.
- Every reviewed MES candidate currently fails promotion.
- The frozen ORB candidate has -$3.45 doubled-cost expectancy and 0.9064 profit factor over 22 untouched trades.

## New Files

- `scripts/topstepx_trade_reconciliation.py`
- `research/topstep_prior_date_router.py`
- `scripts/topstep_readiness_report.py`
- `scripts/run_topstep_evidence_pipeline.ps1`
- `research/TOPSTEP_MES_EXECUTION_EVIDENCE_2026-08-17.md`
- `agent/tests/test_topstepx_reconciliation_upgrade.py`
- `agent/tests/test_topstep_prior_date_router.py`
- `agent/tests/test_topstep_readiness_report.py`

## Modified File

- `strategies/topstepx_practice_adapter.py`
  - Added read-only `search_orders()` and `search_trades()` wrappers for official ProjectX endpoints.
  - Existing order placement, one-MES cap, entry window, kill switch, and practice-only tripwires were not weakened.

## Generated Reports

- `data/topstep_prior_date_route.json`
- `data/topstepx_practice_reconciliation.json`
- `data/topstep_readiness_report.json`

Current readiness blockers:

1. `topstepx_credentials_missing`
2. `personal_device_confirmation_missing`
3. `market_recorder_not_collecting`
4. `no_broker_confirmed_round_trips`
5. `no_strategy_passed_promotion_gate`

## Claude Tasks

1. Do not enable or call any order method.
2. Help Kenny configure ProjectX locally without printing or committing credentials.
3. Run the read-only probe and recorder from the personal device only.
4. Verify recorder quote/trade/depth completeness and p50/p99 timestamp latency.
5. Populate `data/topstep_forward_candidate_outcomes.jsonl` only from frozen, prior-registered shadow candidates with doubled-cost P&L.
6. Run `scripts/run_topstep_evidence_pipeline.ps1` and inspect the consolidated blockers.
7. Require at least 60 forward outcomes across three months and a positive doubled-cost holdout before proposing any separate Practice-order approval.
8. Model real-time unrealized MLL excursions; end-of-day P&L alone is an optimistic risk estimate.

## Verification

Verification completed:

- Targeted Topstep suite: 34 passed.
- Full repository suite: 4,771 passed, 4 skipped.

No orders were submitted.
