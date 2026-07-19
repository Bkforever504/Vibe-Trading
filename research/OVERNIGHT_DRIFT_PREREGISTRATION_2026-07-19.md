# Preregistration: Equity Overnight Drift (Close-to-Open)

Date: 2026-07-19
Status: frozen before any data inspection for this hypothesis
Owner: Claude (research only, no execution)

## Hypothesis

U.S. equity index ETFs earn a disproportionate share of total return in the
overnight session (buy at close, sell at next open). If the effect survives
realistic retail costs, it is a candidate for a small-account systematic lane.

This is an independent mechanism from all previously tested families (ORB,
pullback, close momentum, close reversal, RSI2, momentum rotation).

## Frozen Test Specification

- Instruments: SPY and QQQ only.
- Signal: unconditional. Long at every regular-session close, exit at next
  regular-session open. No filters of any kind.
- Position: 100% of a $1,000 model account per trade, fractional shares.
- Costs: 0.01% per side (Alpaca zero commission, ~1 cent spread on SPY/QQQ),
  stress at 2x (0.02% per side) and 3x.
- Data: daily OHLC, auto-adjusted, from yfinance. 2000-01-01 through latest.

## Chronological Splits (sequential gating)

- Development: 2000-01-01 to 2015-12-31, evaluated in three sub-regimes
  (2000-2005, 2006-2010, 2011-2015).
- Selection: 2016-01-01 to 2020-12-31. Only evaluated if development passes.
- Final: 2021-01-01 to present. Only evaluated if selection passes.

## Pass/Fail Gates (all frozen)

Development: mean per-trade return after base costs positive in all three
sub-regimes for at least one of the two symbols.

Selection (for that symbol): positive total return after base costs, positive
after 2x costs, and max drawdown no worse than -25% of account.

Final: positive after base costs, positive after 2x costs, profit factor of
daily P&L at least 1.05, max drawdown no worse than -25%.

## Explicit Limits

- Two symbols, one rule, zero parameters searched. No grid.
- If the gates fail, the family is recorded as rejected. No filter will be
  added afterward to rescue it on the same data.
- Passing historical gates permits paper forward-testing only, never live
  execution without Kenny's explicit approval.
