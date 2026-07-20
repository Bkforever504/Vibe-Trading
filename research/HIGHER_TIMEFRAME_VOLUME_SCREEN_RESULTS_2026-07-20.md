# Higher-Timeframe Volume Screen Results

Date: July 20, 2026

## Decision

Do not promote higher-timeframe relative volume into execution. Keep completed
weekly and monthly volume expansion as read-only scanner context.

No volume variant passed every preregistered gate. The closest candidate,
weekly RVOL at least 1.25 with weekly/monthly trend alignment, improved final
expectancy but retained a slightly negative 95% bootstrap lower bound.

## Edgeful Assessment

Edgeful is useful as a research workflow and hypothesis generator. Its useful
ideas are conditional historical statistics, session/range reports, a
multi-ticker screener, Monte Carlo analysis, drawdown analysis, and prop-firm
simulation. It is not a live order-flow feed or options-chain intelligence.

Official references:

- https://www.edgeful.com/blog/posts/what-is-edgeful
- https://www.edgeful.com/
- https://help.edgeful.com/en/articles/14288230-screener-filtering-and-customizing-the-data-table
- https://www.edgeful.com/blog/posts/wip-vs-screener-breakdown-building-a-trading-bias

The project now reproduces the relevant methodology without buying a
subscription: preregistration, point-in-time screens, date-level portfolios,
stress costs, top-outlier removal, and moving-block bootstrap. Edgeful may
still save research time, but its subscription is not evidence of an edge.

Recent social evidence was thin. The last-30-days search returned one unrelated
Reddit thread, X access was blocked, and YouTube results were unavailable. No
social claim was used as validation.

## Frozen Experiment

- Universe: 29 fixed liquid ETFs and stocks.
- Development: 2015-2022.
- Selection: 2023.
- Final labeled test: 2024 onward.
- Entry: next session open after a completed weekly or monthly bar.
- Portfolio: at most five symbols, equal-weighted by decision date.
- Costs: 10 bps round trip; 30 bps stress.
- Weekly hold: five sessions.
- Monthly hold: twenty sessions.

The current-symbol universe creates survivorship bias, and Yahoo adjusted bars
are research data rather than executable quotes.

## Results

| Variant | Dev exp. | 2023 exp. | 2024+ exp. | 30 bps stress | Top 1% removed | Bootstrap low | Final uplift |
|---|---:|---:|---:|---:|---:|---:|---:|
| Weekly price trend baseline | 18.51 bps | 67.79 | 39.02 | 19.02 | 25.24 | -14.20 | baseline |
| Weekly RVOL >= 1.25 | 31.85 | 62.67 | 38.97 | 18.97 | 29.56 | -16.97 | -0.05 |
| Weekly volume acceleration | 25.22 | 66.99 | 42.72 | 22.72 | 27.78 | -24.81 | +3.70 |
| Weekly RVOL >= 1.25 + dual trend | 64.16 | 38.45 | 58.88 | 38.88 | 48.93 | -0.12 | +19.86 |
| Monthly price trend baseline | 225.10 | 263.27 | 297.73 | 277.73 | 252.03 | +0.91 | baseline |
| Monthly RVOL >= 1.25 | 36.14 | -130.42 | 109.27 | 89.27 | 46.53 | -269.80 | -188.46 |

All expectancies are per decision-date portfolio. Final sample counts were 132,
93, 112, 86, 30, and 21 respectively.

## Interpretation

Weekly volume plus dual trend is a credible forward-shadow hypothesis, not a
validated edge. It passed direction, costs, outlier removal, and baseline
uplift, but failed the uncertainty gate by 0.12 bps. Monthly volume expansion
was actively harmful relative to monthly price trend and was negative in 2023.

The monthly price-trend baseline passed its historical gates, but it was not a
new preregistered strategy family and is exposed to severe current-universe
survivorship bias. It must not be promoted from this experiment.

## Integration

`scripts/deep_liquid_universe_scanner.py` now records completed weekly and
monthly relative volume and trend state. It exposes expansion candidates in a
separate context-only list. These fields do not change trading scores, do not
change existing strategies, and cannot submit orders.
