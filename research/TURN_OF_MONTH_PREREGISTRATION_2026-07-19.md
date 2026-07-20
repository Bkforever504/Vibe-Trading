# Preregistration: Turn-of-Month Equity Effect

Date: 2026-07-19
Status: frozen before running any simulation
Owner: Claude (research only, no execution)

## Hypothesis

Equity index returns concentrate in the turn-of-month window (institutional
flows: pension contributions, rebalancing, salary sweeps). Holding SPY/QQQ
only during the last 4 and first 3 trading days of each month captures most
of the market's return with a fraction of the exposure.

## Frozen Test Specification

- Instruments: SPY and QQQ only.
- Rule: long from the close of the 5th-to-last trading day of the month to
  the close of the 3rd trading day of the next month. Flat otherwise.
  No other filters. Zero parameters searched.
- Position: 100% of a $1,000 model account, fractional shares.
- Costs: 0.01% per side per round trip (one entry, one exit per month);
  stress at 2x and 3x.
- Data: daily closes, auto-adjusted, yfinance, 2000-01-01 to latest.
- Benchmark comparison: buy-and-hold same period (context only, not a gate).

## Splits and Sequential Gates

- Development: 2000-2015 in three sub-regimes (2000-2005, 2006-2010,
  2011-2015). Gate: positive total return after base costs in all three
  sub-regimes for at least one symbol.
- Selection (that symbol): 2016-2020. Gate: positive after base and 2x
  costs, max drawdown no worse than -25%.
- Final: 2021+. Gate: positive after base and 2x costs, PF >= 1.05,
  max drawdown no worse than -25%.

## Explicit Limits

- Two symbols, one rule. If gates fail, family is rejected; no window
  tuning afterward on this data.
- A pass permits paper forward-testing only. It does not change the
  honest $1,000 math: no historical anomaly turns $1,000 into $100/day.
