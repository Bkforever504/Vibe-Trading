# $1,000 Account Policy - 2026-07-19

## Objective

Grow a $1,000 account without using account-size fiction, whole-contract leverage, or a daily-income target.

## Current Decision

- Flip SPY options: paper observation only for the $1,000 lane.
- Lead small-account candidate: frozen 12-month top-two ETF momentum.
- Deployment: 50% across the two selected ETFs using fractional shares, 50% cash.
- Per-trade options risk budget: 2%, or $20.
- Target model drawdown: no more than 8% before manual review.
- Isolated virtual paper ledger: active.
- Broker and live execution: disabled.

## Evidence

- Current Alpaca paper account: approximately $89,836. It does not represent the intended $1,000 capital constraint.
- Historical post-hardening SPY option premiums: $68 to $161 for one contract.
- Contracts fitting a $20 full-premium risk budget: 0 of 12.
- Contracts whose planned 30% stop fits $20: 0 of 12.
- One-contract historical scaling: $1,000 to $1,404.60 with an 11.36% drawdown. This is not executable 2% sizing and is consumed evidence.
- Half-deployed momentum 2025+: +21.25%, 6.67% maximum drawdown.
- Half-deployed momentum at double costs: +20.56%.

## Promotion Gate

Require at least 26 weekly point-in-time decisions with broker-executable fractional-share prices. Compare actual shadow fills with the model, include turnover costs, and require positive expectancy with drawdown at or below the policy limit.

The virtual ledger runs daily at 8:40 AM Central for valuation and the drawdown halt. It rebalances only on the first open session of each ISO week. State is isolated from the shared Alpaca paper account at `~/.vibe-trading/state/micro-momentum-paper.json`.

## Launch Status

- Scheduled task: `\VibeTrade\MicroMomentumPaper`
- First executable session: Monday, July 20, 2026 at 8:40 AM Central
- Current signal as of July 17: XLE and XLK
- Initial targets: $250 XLE, $250 XLK, $500 cash
- Strategy confidence: 6.5/10; promising but not live-proven
- Small-account operational fit: 9/10
- Automatic live promotion: prohibited

The consumed 2025+ result annualized to 13.44%, which is about $134 per year on $1,000 before taxes if repeated. It is not a dependable income stream and must not be marketed or treated as one.

Do not promote based on the existing historical extension or on a desire to generate daily income.
