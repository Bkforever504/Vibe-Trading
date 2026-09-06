# Trader Barbie STRAT/SMC/ICT composite — preregistration

Status: frozen shadow experiment. No rank, sizing, alert, or execution authority.

## Frozen hypothesis

A causal 15-minute liquidity sweep plus close-back-inside, aligned with the
dealing-range 50% equilibrium and a STRAT directional bar, may improve the
precision of the existing liquidity-sweep family without materially reducing
recall.

## Frozen rules

- BSL/SSL proxy: rolling 20-bar confirmed high/low, shifted one bar.
- Sweep: high exceeds prior BSL and closes below it (bearish), or low breaks
  prior SSL and closes above it (bullish).
- CE: midpoint of the prior 20 completed 15-minute bars. Longs require the
  signal close at/below CE; shorts require it at/above CE.
- STRAT direction: the bar immediately after the sweep is 2U for long or 2D
  for short relative to the completed sweep bar. Outside bars and inside bars
  do not qualify in v1.
- Entry: next 15-minute open. Stop: signal extreme. Target: 2R. If stop and
  target are both touched in one bar, stop wins.
- Costs: 2 bps round trip for ETF underlying research only. No option return is
  inferred.
- Split: chronological first 70% development, final 30% untouched holdout.

## Promotion gates

At least 50 completed signals, 10 trading dates, 15 holdout signals, positive
holdout expectancy after costs, and no material degradation in recall. Passing
these gates permits further shadow study only.
