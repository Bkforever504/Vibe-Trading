# Swing Risk Overlay Preregistration

Date: 2026-08-13
Status: frozen before variant outcomes are computed
Mode: research only; no order authority

## Baseline

Monthly top-five momentum portfolio from the existing higher-timeframe lab:

- Liquid technology/AI universe: SPY, QQQ, SMH, XLK, AAPL, MSFT, NVDA,
  AMZN, META, GOOGL, TSLA, AMD.
- At each completed month end, require positive monthly return and close above
  its trailing 10-month average.
- Rank by trailing three-month momentum.
- Enter at the next session open and exit after 20 trading sessions at close.
- Equal weight, long only, no leverage.

## Frozen Overlays

No parameter sweep is permitted. These economically motivated variants are
fixed before outcomes are opened:

1. `equal_weight_baseline`: unchanged baseline.
2. `inverse_volatility`: weight selected assets by inverse 20-session realized
   volatility, with a 35% maximum position weight. If fewer than three assets
   qualify, each remains capped at 35% and the residual stays in cash.
3. `spy_200d_regime`: full exposure only when SPY's completed close is above
   its completed 200-session SMA; otherwise cash.
4. `breadth_scaled`: exposure 100% when at least 60% of the universe is above
   its 200-session SMA, 50% when breadth is 40-60%, otherwise cash.
5. `dual_daily_trend`: retain candidates only when close is above the 200-day
   SMA and the 50-day SMA is above the 200-day SMA.
6. `combined_risk_overlay`: inverse-volatility weights plus breadth scaling and
   a virtual-baseline drawdown throttle. Exposure is multiplied by 50% below
   an 8% virtual drawdown and by 0% below a 15% virtual drawdown. Recovery is
   determined from the unthrottled baseline equity, avoiding a permanent cash
   lockout.

All indicators use information available at the completed decision close.
Entries remain next-open. Ordinary round-trip cost is 10 bps; stress cost is
30 bps, charged in proportion to invested exposure. Only fully resolved
20-session holding windows are scored.

## Chronology

- Development: 2015-2022.
- Selection diagnostic: 2023-2025.
- Final diagnostic: 2026 through cached data ending 2026-07-20.

The 2026 period is not a pristine holdout because the baseline's aggregated
2024+ result has already been viewed. No overlay-specific 2026 result has been
viewed, so it remains a sealed variant comparison but not independent proof.

## Success Gates

Relative to equal-weight baseline, a candidate must:

- Reduce maximum drawdown by at least 20% in development and 2023-2025.
- Increase ending equity in 2023-2025.
- Preserve positive expectancy under 30-bps costs in every period.
- Preserve positive expectancy after removing the best 1% of periods.
- Have positive bootstrap lower-bound expectancy in development.
- Avoid any single position above 35% where weighted.

Passing permits a shadow-only forward portfolio. It cannot authorize broker,
paper, prop-firm, or live orders.
