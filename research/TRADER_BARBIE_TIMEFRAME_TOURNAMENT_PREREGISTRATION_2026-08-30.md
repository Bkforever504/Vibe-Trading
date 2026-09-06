# Trader Barbie timeframe tournament — preregistration

Frozen before running the tournament. Research/shadow only.

- Candidate bar sizes: 5, 10, 15, 30, and 60 minutes. These are the only
  resolutions recoverable without fabricating detail from the available
  five-minute SPY/QQQ source.
- The complete cocktail is evaluated at each resolution; no thresholds change.
- A second, faithful lane keeps BSL/SSL, CE, and support/resistance on 15-minute
  bars while varying only the STRAT confirmation/entry bar size.
- Three chronological walk-forward folds are reported independently.
- A candidate must have at least 50 total test trades, positive mean net R,
  profit factor above 1, and positive expectancy in at least two of three folds.
- Family-wise error is controlled with Bonferroni alpha 0.05 / 5. The p-value is
  diagnostic only and cannot override the economic gates.
- The previously inspected 15-minute period is considered contaminated for
  promotion. This tournament may select a forward-shadow challenger, never a
  live or ranking-authorized rule.

## Post-result coarse extension

After the frozen 5–60 minute matrix showed monotonic improvement toward 60
minutes, a separate exploratory extension was declared for 90, 120, and 240
minutes. Because this extension was motivated by observed results, its entire
historical output is selection-contaminated and may only choose a future
forward-shadow challenger.
