# Fibonacci Method And Results - 2026-08-16

## Correct Use Implemented

- Anchor the prior meaningful directional move from confirmed trough to peak
  for an up impulse, and peak to trough for a down impulse.
- Confirm swing endpoints causally with an ATR-ZigZag; never use a future-visible
  high or low.
- Treat 38.2%, 50%, and 61.8% as alert zones, not automatic predictions.
- Separate level touch, rejection, trend, VWAP, and volume so each tool's
  incremental effect can be measured.
- Use next-bar fills, stop-first ambiguity, and modeled costs.
- For a confirmed setup, test a limit at the retracement level rather than
  chasing the post-confirmation market price.

This follows the basic peak/trough construction described by
[Fidelity](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/fibonacci-retracement)
and [CME Group](https://www.cmegroup.com/education/courses/technical-analysis/fibonacci-retracements-and-extensions.hideSubnav.educationIframe.html?hideAddThisExt=y&hideFooter=y&hideHeader=y&hideRightRail=y).
CME explicitly describes the ratios as alert zones and recommends using them
with other evidence rather than in isolation.

## Evidence Warning

The peer-reviewed three-market study by Tsinaslanidis, Guijarro, and Voukelatos
found Fibonacci zones statistically indistinguishable from non-Fibonacci zones
and found no standalone abnormal-profit support:
[DOI 10.1016/j.eswa.2021.115893](https://doi.org/10.1016/j.eswa.2021.115893).
Shanaev and Gibson report conflicting positive cross-sectional evidence:
[SSRN 4212430](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4212430).
That disagreement requires local placebo and out-of-sample testing.

## Backtests

V1 used adjacent local pivots and a 0.786 stop. It failed. V2 corrected the
anchor with a causal ATR-ZigZag and moved the stop beyond the swing origin. It
also failed across SPY, QQQ, and IWM.

V3 used a next-bar limit at the exact retracement level. On SPY from 2025 onward,
the 0.618 trend-confirmed stage produced 24 trades, +0.336R expectancy, 62.5%
winners, and 1.689 profit factor. It remained positive at doubled modeled cost.
However, it was negative in 2020-2023 development, negative in 2024 selection,
negative on QQQ, and below the 40-trade minimum. It therefore failed promotion.

## Tool Attribution

- Fibonacci touch alone: negative.
- Rejection candle: negative.
- Trend confirmation: positive only in the recent small SPY slice.
- VWAP: no incremental information; it selected the same recent 24 SPY trades.
- Relative volume: reduced the sample to 16 and did not improve expectancy.

The correct production state is mandatory structural telemetry with no
directional or sizing authority. The trend-plus-limit variant may collect paper
shadow evidence, but cannot block trades, submit orders, or increase size.

## V4 Execution Follow-up

The preregistered no-chase execution tournament is documented in
`research/FIBONACCI_EXECUTION_RESEARCH_2026-08-17.md`. No 0.618, 0.650,
0.705, 0.786, or placebo 0.550 variant passed development and selection.
Longer order TTLs degraded the recent SPY result. The one-bar 0.618 benchmark
therefore remains shadow-only and expires without market conversion.
