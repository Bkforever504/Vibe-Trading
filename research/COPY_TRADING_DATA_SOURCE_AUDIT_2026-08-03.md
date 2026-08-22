# Copy Trading Data Source Audit

Date: 2026-08-03
Scope: systematic options research and forward shadow copying

## Decision

No external trader is approved for live copying. The usable hierarchy is:

1. Robinhood Social verified trade posts for timely candidate signals.
2. Kinfo broker-imported profiles for historical PnL verification.
3. Consented, complete broker exports for outcome and drawdown validation.
4. SEC Form 4 and CFTC COT records for delayed context only.

Collective2 and ordinary social-media posts are hypothesis sources, not proof
of live profitability.

## Source Audit

| Source | What is reliable | Critical limitation | System use |
|---|---|---|---|
| Robinhood Social | Platform-verified users and shared trades; entry/exit activity can be live | Sharing can be selective; public product materials describe one-year and daily PnL, not immutable full-account coverage | Timely shadow signal only, with exact contract, timestamp, leader price, current executable quote, and under 5% drift |
| Kinfo | Broker-imported closed trades cannot be manually added, removed, or edited; paper accounts lose the Verified mark | Traders may hide executions; linked-account coverage and real-time signal latency are not proven by the public profile | Verify historical PnL and losses; never create a signal from hidden or delayed trades |
| Consented broker export | Exact fills, fees, losses, and position lifecycle | Requires trader cooperation and a coverage manifest proving the export is complete | Highest-quality replay and outcome evidence |
| Collective2 | Public strategy signal history and complete displayed model record | Collective2 states all displayed results are hypothetical and model fills can differ from subscriber fills | Research hypothesis only |
| SEC Form 4 | Authoritative insider transactions, generally reported promptly | Delayed and not a trader strategy; no useful options execution detail | Swing context only |
| SEC Form 13F | Authoritative institutional holdings | Up to 45 days after quarter-end; no complete short book or entry timing | Slow allocation context only |

## Public Options Profiles Reviewed

| Profile | Verified evidence | Why it is not copy-ready |
|---|---|---|
| HL Financial Strats (Kinfo 16790) | Broker-verified options history with visible recent symbols and losses included by platform design | Public page does not establish complete account coverage, exact live timestamps, max drawdown, or small-account collateral fit |
| Bobdog (Kinfo 60674) | Broker-verified realized PnL and win/loss history | Contracts are redacted; cash-secured-put collateral and tail assignment risk do not fit a $500-$1,000 account |
| Ravish (Kinfo 66957) | Broker-verified aggregate PnL and win rate | Trades are hidden, so execution and strategy replication cannot be audited |
| N32154 (Kinfo 97253) | Broker-verified options outcomes shown publicly | Concentrated leveraged ETF options and incomplete visible risk history make the apparent returns non-portable |

These profiles are research leads, not endorsements.

## Fixed Qualification Gate

A trader can enter `paper_watch` only after all of the following are present:

- broker or platform verification
- immutable coverage proof and all losses included
- at least 100 closed trades across at least 60 distinct trading days
- fee- and spread-adjusted profit factor at least 1.30
- positive expectancy under observed copy delay and doubled costs
- maximum drawdown no greater than 15%
- at least 95% defined-risk trades
- exact contracts visible and median signal delay no greater than 300 seconds

Each copied observation must be repriced at the executable ask for buys and bid
for sells. Leader midpoint or screenshot prices are not accepted. The first 100
qualified observations remain local paper trades. No source can enable order
submission or change production sizing.
