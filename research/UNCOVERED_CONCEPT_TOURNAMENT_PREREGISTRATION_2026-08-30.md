# Uncovered concept tournament — preregistration

Frozen before results on 2026-08-30. Historical research only.

## Why this exists

The concept-coverage audit found that dashboard implementation and partial proxy
coverage had been mistaken for isolated validation. This experiment tests four
distinct, data-ready gaps instead of adding filters to a previously selected
winner.

## Frozen families

1. `cbc_strong_flip`: one completed bar sweeps both extremes of the previous
   completed bar and closes beyond one of those extremes.
2. `session_liquidity_sweep_reclaim`: after the first 30 RTH minutes, sweep and
   close back through a causal PDH, PDL, ORH, or ORL.
3. `engulfing_context_gated`: reversal body engulfs the prior body after a
   five-bar trend, volume is at least 1.2 times its prior 20-bar mean, and the
   next completed bar confirms beyond the engulfing extreme.
4. `fvg_retest_trend_proxy`: three-bar imbalance created by a displacement body
   of at least 0.7 ATR, aligned with execution-timeframe EMA 8/21, followed by a
   midpoint retest/rejection within six bars. The `_proxy` suffix is mandatory:
   execution-timeframe EMA alignment is not true higher-timeframe direction.

## Frozen matrix and execution

- Cross-market matrix: SPY and QQQ on 5m and 15m completed RTH bars.
- Exploratory resolution: SPY 3m using genuine 1m source data; it is ineligible
  for cross-market status because equivalent QQQ 1m history is unavailable.
- One first qualifying signal per family/session.
- Entry at the next completed-bar open; detector extreme/boundary is the stop;
  2R target; 60-minute maximum hold; stop wins same-bar ambiguity.
- Friction: 4 bps round trip on $10,000 underlying notional; 8 bps stress.
- Three chronological folds.

## Gates

Each market trial requires at least 60 trades, positive expectancy, PF above
1.10, positive doubled-friction expectancy, two positive folds, and one-sided
p-value below `0.05 / 1012`. A family/timeframe may enter prospective shadow
only if the identical 5m or 15m rule passes in both SPY and QQQ. Historical
results have no scanner-rank, A+/B+ alert, sizing, options-return, or order
authority.

