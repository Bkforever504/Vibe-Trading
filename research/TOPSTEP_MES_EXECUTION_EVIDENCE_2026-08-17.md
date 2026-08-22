# Topstep MES Execution and Evidence Audit

Date: 2026-08-17

## Verdict

The Topstep stack has strong practice-account safety controls but is not ready to trade. Current blockers are operational and statistical:

- TopstepX username, API key, practice account ID, and local-device confirmation are not configured in `agent/.env`.
- The ProjectX market recorder is blocked and has collected no MES quote, trade, or depth events.
- There are no broker-confirmed practice round trips.
- No frozen MES strategy has passed the forward, doubled-cost, and Combine-risk promotion gate.

The frozen ORB candidate made $12 over 22 untouched trades at base costs but lost $76 at doubled costs. Its profit factor fell from 1.0159 to 0.9064. The current decision remains `do_not_purchase_combine`.

## Official Rule Corrections

The implementation must model these current Topstep requirements:

1. The 50K Trading Combine has a $3,000 profit target and $2,000 Maximum Loss Limit.
2. The MLL trails the end-of-day balance high-water mark, but it is enforced intraday against realized plus unrealized P&L.
3. The best day should remain at or below 50% of total profit; exceeding it increases the effective target.
4. MES costs $1.22 round turn on TopstepX before spread and slippage.
5. API automation must run from the trader's personal device. VPN, VPS, and remote-server operation are prohibited.
6. Simulator queue, latency, stop-fill, and rapid-scalping exploitation are prohibited and cannot be used as strategy evidence.
7. Topstep's free Practice account requires an active Trading Combine. ProjectX API access is separately billed and has no dedicated API sandbox.

Official sources:

- https://help.topstep.com/en/articles/8284197-trading-combine-parameters
- https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit
- https://help.topstep.com/en/articles/8284208-consistency-at-topstep
- https://help.topstep.com/en/articles/11187768-topstepx-api-access
- https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep
- https://help.topstep.com/en/articles/8284213-topstepx-commissions-and-fees
- https://gateway.docs.projectx.com/docs/api-reference/trade/trade-search/
- https://gateway.docs.projectx.com/docs/api-reference/order/order-search/

## Implemented Controls

### Broker-confirmed reconciliation

`scripts/topstepx_trade_reconciliation.py` reads official order and half-turn trade history. It FIFO-pairs MES fills, independently calculates point-value P&L and fees, preserves the broker-reported P&L separately, and refuses to resolve local journal or replay outcomes.

### Executable trade shape

For each broker-confirmed round trip, the report uses the liquidation side of the quote:

- Long position: executable bid.
- Short position: executable ask.

It records MFE, MAE, first confirmation, never-confirmed entries, adverse recovery, winner giveback, and failed-after-profit behavior. Missing quote coverage stays `incomplete`.

### Prior-date routing

`research/topstep_prior_date_router.py` can route only forward-shadow candidates. It excludes same-day and future rows and requires:

- 30 resolved outcomes minimum.
- Positive doubled-cost expectancy.
- Positive 90% lower confidence bound on expectancy.
- Profit factor at least 1.20.
- Maximum drawdown no greater than $500.

Passing this router is observation authority only. It is not Practice or Combine approval.

### Consolidated readiness

`scripts/topstep_readiness_report.py` combines credentials, recorder status, broker reconciliation, candidate promotion contracts, and the prior-date route. Any missing component blocks readiness.

## Next Operating Sequence

1. Configure ProjectX credentials and the exact personal-device confirmation locally. Never commit or paste the API key.
2. Run the read-only practice probe.
3. Run the MES market recorder during RTH until quote/trade/depth completeness and latency pass.
4. Run `scripts/run_topstep_evidence_pipeline.ps1` daily.
5. Accumulate frozen forward-shadow candidate outcomes with doubled costs.
6. Do not purchase a Combine or permit Practice orders until a candidate passes the promotion contract and the broker reconciliation is complete.

No orders were submitted by this work.

