# Multi-timeframe edge tournament — preregistration

Frozen before reading tournament results on 2026-08-30.

## Question

Do any of the eight intraday families previously tested only on 5-minute bars retain positive net expectancy when evaluated on 5, 10, 15, 30, and 60-minute bars in both SPY and QQQ?

## Frozen design

- Families: opening-range breakout/retest, prior-day break/retest, liquidity sweep + MSS + FVG, first-touch RSI fade, gap continuation, EMA 8/21 break/retest, opening-drive VWAP pullback, and multi-indicator reversal.
- Markets: SPY and QQQ.
- Timeframes: 5, 10, 15, 30, and 60 minutes.
- Exit: fixed 2R target, signal-defined stop, conservative stop-first ordering when both are touched, and a fixed 60-minute maximum hold.
- Entry: next completed bar open. Signals after 14:30 ET are excluded.
- Friction: 4 bps round-trip on $10,000 notional; stress test uses 8 bps.
- Data: completed regular-session OHLCV only. No options-premium claims are inferred from underlying returns.
- Validation: three chronological folds, minimum 60 aggregate trades, at least two positive folds, aggregate expectancy above zero, profit factor above 1.10, positive expectancy under doubled friction, and one-sided mean-test p-value below the cumulative Bonferroni threshold.
- Cross-market robust status requires the identical family/timeframe pair to pass in both SPY and QQQ.

## Multiple testing and promotion

The 80 new market/family/timeframe trials are added to the 909 effective attempts already counted by the global social-sequence program. Alpha is `0.05 / 989`. Every result is selection-contaminated historical research and has no live ranking, alerting, sizing, or order authority. A survivor may only enter a separately logged forward-shadow lane; it cannot be promoted from this tournament.

