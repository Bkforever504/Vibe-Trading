# Dashboard Operational Readiness — 2026-08-23

## Outcome

The scanner/dashboard evidence chain is build-complete and deployed as schema v11. It remains read-only:

- `execution_enabled=false`
- `can_submit_orders=false`
- no bot bodies or broker order paths changed
- authenticated gateway rejects write methods with HTTP 405

“100%” is split into three honest measures instead of one misleading score:

1. **Build:** 100% installed.
2. **Runtime:** 62.5% on Sunday 2026-08-23.
3. **Evidence:** collecting; no ranking-qualified probability bucket yet.

The system is therefore installed, but it is not currently claiming that live evidence is fully ready for manual review.

## Delivered

- Independent frozen-spec MOVE builder for SPY, QQQ, IWM, MES, ES, and NQ across 5m, 15m, 1h, and daily.
- Alpaca IEX/SIP ETF bars plus cost-gated Databento `GLBX.MDP3` continuous futures bars.
- Explicit RTH/ETH separation, causal ATR, horizon maturity, macro exclusions, stop-first ambiguity handling, and source-condition exclusions.
- Fixed the Markdown approval-marker parser that had incorrectly kept the approved MOVE spec in placeholder mode.
- Detection scorecard now separates price-opportunity coverage, independent pattern annotation metrics, and resolved family outcome quality.
- Options-feed qualification with provider, entitlement, freshness, OPRA/indicative, size, and maximum-spread gates.
- Append-only manual execution-quality evidence and GET-only broker-fill observation/linkage.
- Dashboard schema v11 readiness gate and execution-quality panel.
- Daily A+ review denominator now includes MOVE, scorecard, calibration, options feed, manual execution quality, and broker fills.
- Intraday and post-close read-only scheduled evidence tasks registered at Limited run level.
- Synthetic end-to-end evidence-chain proof.

## Real Provider Proof

The bounded Friday 2026-08-21 probe used existing Alpaca and Databento configuration and submitted no orders.

- Provider cost estimate: approximately $0.49 total for the three 45-day Databento futures requests.
- Instrument/timeframe pairs reconciled: 24.
- Causal label rows: 1,559.
- Labeled directional moves: 175.
- Mature intraday pairs: 18.
- Daily pairs awaiting the frozen three-day horizon: 6.
- Producer health: healthy.
- Global metrics qualification: pending daily horizon maturity.

Databento reported 2026-07-30 as degraded. Future scheduled runs exclude non-available dataset-condition dates and retain that provenance.

## Current Visible Runtime Blockers

- `pattern_scanner`: Sunday report has one producer failure because no current market snapshot was available.
- `options_feed_gate`: 14 retained quotes are stale Alpaca indicative quotes; none is current entitled OPRA.
- `daily_aplus_review`: 95.7% source coverage, blocked only by the failed pattern-scanner status.
- `execution_quality`: two broker fills were observed and both remain unmatched to canonical detection plans.
- `probability_calibration`: still collecting; setup grades are not win probabilities.

The weekday schedulers will refresh the first three. The two unmatched fills require human linkage/review; they are not silently assigned.

## Verification

- Agent suite: **5,201 passed, 4 skipped**.
- Focused backend/integration suite: **172 passed**.
- Frontend: **219 passed**.
- Frontend production build: passed.
- Synthetic evidence chain: passed.
- `execution_gate_audit.py --fail-on-issues`: passed, zero order-authority issues.
- Python compilation: passed.
- `git diff --check`: passed.
- Live backend: authenticated schema v11, build 100%, runtime 62.5%, execution flags false.
- Remote gateway: authenticated schema v11; POST returns 405.

## Scheduled Tasks

- `VibeTradingMoveGroundTruth` — existing 16:30 CT producer, upgraded to the frozen causal builder.
- `VibeTradingDashboardEvidencePostClose` — 16:45 CT weekday scorecard/calibration/review/readiness chain.
- `VibeTradingDashboardEvidenceIntraday` — 15-minute read-only feed/fill/readiness observation.
- Existing Pattern Grader and Daily A+ Review tasks remain Ready and Limited.

The post-close chain consumes the 16:30 MOVE report and does not redownload paid futures data.
