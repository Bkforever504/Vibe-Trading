# Breakaway FVG + Structure Proxy Results

Date: 2026-08-04
Mode: research only; no execution

## Vendor Evidence Review

The public product pages describe a TradingView strategy using fair-value-gap
entries after structural breaks, routed by webhook to Tradovate with automatic
stops, targets, and breakeven management. Public customer reviews and funded
evaluation screenshots exist, but no cost-adjusted trade ledger, drawdown
series, exact rules, or independently verified broker return history was found.

Customer satisfaction and passed-evaluation screenshots do not establish the
bot's expectancy, survivorship rate, or risk of ruin.

## Frozen Proxy Test

Protocol:
`research/BREAKAWAY_FVG_STRUCTURE_PREREGISTRATION_2026-08-04.md`

Report: `data/breakaway_fvg_structure_results.json`

- Dataset: 1,148 corrected MES RTH sessions.
- Development: first 803 sessions in three chronological regimes.
- Rule: six-bar structural close break, displacement body and volume,
  same-bar four-tick FVG, midpoint retrace, structural stop, 2R target,
  breakeven after 1R, one trade per day, realistic two-sided costs.
- Development signals: 1.
- Before-cost result: breakeven.
- After-cost result: -$4.98.
- Doubled-cost result: -$9.96.
- Development gate: failed for insufficient incidence and negative expectancy.
- Selection opened: no.
- Final opened: no.

## Conclusion

The disclosed marketing description is too incomplete to reproduce a useful
strategy. The literal high-quality conjunction is extremely rare, while the
broader FVG rule was already tested on 696 development trades and failed
stability in the newest regime (PF 0.94).

Do not buy, copy, or promote the strategy from screenshots. A legitimate
comparison requires an export containing timestamp, instrument, direction,
entry, stop, target, exit, quantity, fees, and all losing/failed trades. That
ledger can be ingested into the existing verified-trader shadow pipeline and
evaluated without granting execution authority.

The vendor is ahead in packaging and turnkey routing. There is no available
evidence that it is ahead in cost-adjusted, risk-adjusted profitability.
