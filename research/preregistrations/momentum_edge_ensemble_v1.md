# Momentum Edge Ensemble V1 Preregistration

Status: locked before execution of the ensemble test on 2026-08-17.

## Hypothesis

The repository's broadest cost-tolerant evidence is medium-horizon momentum, not
intraday direction. Combining independently defined absolute and relative
momentum sleeves should preserve positive expectancy while reducing dependence
on one universe, rebalance date, or ranking method.

## Fixed Portfolio

The ensemble has three equal one-third sleeves:

1. Sector 12-month momentum: top three positive-momentum sector ETFs, monthly.
2. Sector low volatility: three lowest 63-day-volatility sector ETFs among
   those with positive 12-month momentum, monthly.
3. Canonical cross-asset momentum: top two positive 12-month-momentum ETFs,
   rebalanced every five trading days.

The sector universe is `XLB XLE XLF XLI XLK XLP XLU XLV XLY`. The canonical
universe is `SPY QQQ GLD XLE TLT IWM XLK XLV XLF XLI`.

Signals use closing data. New weights take effect one trading day later. The
three sleeve weights are averaged, each asset is capped at 35%, and any
unallocated weight remains cash. No leverage and no short positions are used.

## Costs And Windows

- Base cost: 6 basis points per unit of traded notional.
- Stress cost: 12 basis points per unit of traded notional.
- Development: 2007-01-01 through 2021-12-31.
- Selection: 2022-01-01 through 2024-12-31.
- Final diagnostic: 2025-01-01 onward.

The component strategies were selected after these periods had already been
observed. Consequently, the final window is not a pristine holdout and this
test cannot authorize capital.

## Acceptance Gates

All gates must pass:

- Selection CAGR is positive.
- Final diagnostic CAGR is positive.
- Overall Sharpe exceeds same-date SPY buy-and-hold.
- Overall maximum drawdown is lower than same-date SPY buy-and-hold.
- Selection and final maximum drawdowns are each lower than SPY.
- Overall CAGR remains positive at doubled costs.
- Overall CAGR remains positive after setting the best 1% of daily returns to
  zero.
- Maximum asset weight never exceeds 35%.

Passing means `forward_shadow_candidate` only. It does not change sizing,
broker settings, execution flags, or promotion status. A separate forward gate
requires at least 12 completed monthly observations and 252 elapsed trading
sessions before any paper-capital review.

