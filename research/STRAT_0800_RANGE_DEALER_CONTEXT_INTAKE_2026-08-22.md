# STRAT, 08:00 Range, and Dealer-Level Intake

Status: implemented as shadow-only dashboard context; no execution authority.

## Accepted into the dashboard

- Completed-bar STRAT classification: `1`, `2u`, `2d`, and `3` are objective relationships to the prior completed bar.
- Strict FTFC display: bullish or bearish only when at least four supplied completed timeframes are directional and agree. Fewer frames display `incomplete`; disagreement displays `conflict`.
- 08:00-09:00 ET balance range: compute the range only after 09:00 ET, record the first later sweep, then require the existing chronological, closed-body CISD detector to agree with the reversal direction. The opposite range edge is displayed as context, not a guaranteed target.
- Options walls and gamma flip remain provenance-gated context. Open interest cannot reveal dealer inventory or trade direction by itself.

## Rejected claims

- The screenshot's 99.6% range-sweep rate is not used. No accessible primary dataset, denominator, cost model, or out-of-sample protocol was found to reproduce it.
- Social P&L screenshots are not evidence of a strategy's base rate, expected value, or drawdown.
- Call walls, put walls, premium-density strikes, and gamma flips are not standalone entries.

## Sources

- The STRAT publisher's framework description: https://thestrat.ai/docs/the-3-universal-truths-that-govern-price/
- Cboe exchange-level 0DTE market-impact analysis: https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options
- User-supplied social screenshots, 2026-08-22.

Every added payload field hardcodes `execution_enabled=false` and `can_submit_orders=false`. Probability and score effects remain unavailable until local forward outcomes pass the existing governance gates.
