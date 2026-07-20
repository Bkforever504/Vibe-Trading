# Higher-Timeframe Volume Screen Preregistration

Frozen before viewing results on July 20, 2026.

## Hypothesis

For a fixed liquid stock/ETF universe, completed weekly or monthly volume
expansion may improve the next-period return of a price-trend screen. Volume
must beat the corresponding price-only baseline, not merely produce a positive
backtest.

## Fixed Family

- Weekly price-trend baseline.
- Weekly RVOL at least 1.25 with a positive week.
- Weekly volume acceleration with RVOL at least 1.0.
- Weekly RVOL at least 1.25 with weekly and monthly trend alignment.
- Monthly price-trend baseline.
- Monthly RVOL at least 1.25 with a positive month.

Every date selects at most five symbols. Entries occur at the next session open.
Weekly holds last five sessions; monthly holds last twenty sessions. Portfolio
returns are equal-weighted by decision date. Base round-trip friction is 10 bps;
stress friction is 30 bps.

## Windows

- Development: 2015 through 2022.
- Selection check: 2023.
- Final labeled test: 2024 onward.

The final window is new to this exact family but not untouched market history;
other project studies have inspected it.

## Passing Standard

A volume variant is only a research survivor when it:

1. Has positive expectancy in development, selection, and final windows.
2. Improves final expectancy over its price-only baseline.
3. Remains positive at 30 bps round-trip costs.
4. Remains positive after removing the top 1% of period returns.
5. Has a positive 95% moving-block-bootstrap lower bound in the final window.

Passing authorizes forward shadow logging only. It cannot change production or
submit orders.
