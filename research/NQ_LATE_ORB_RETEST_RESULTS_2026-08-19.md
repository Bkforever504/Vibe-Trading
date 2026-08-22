# NQ Late ORB Retest Research Result

Date: 2026-08-19

## Hypothesis

A delayed opening-range breakout can retain directional follow-through when price:

1. Forms a completed 15-minute opening range.
2. Later closes beyond the range by at least 10 NQ points.
3. Closes on the correct side of live session VWAP.
4. Subsequently retests the broken range boundary.
5. Rejects that boundary while remaining on the correct side of VWAP.

The entry is the completed retest bar close. Wick-only breaks, same-bar retests,
future-bar inspection, and chase entries are prohibited.

## Frozen Test Configuration

- Instrument: NQ/MNQ or MES, depending on the dataset.
- Bars: 5-minute for NQ; source-native intraday bars for MES replay.
- Opening range: first 15 minutes.
- NQ minimum breakout: 10 points.
- NQ stop: 80 ticks.
- Targets tested: 1.5R and 2.0R.
- Costs: commissions and slippage included by the existing replay engine.
- Split: chronological development and holdout periods.

## Results

### MES, 2022-2026

The sequence did not survive. Representative 15-minute opening-range results:

| Variant | Development expectancy | Holdout expectancy | Holdout PF |
| --- | ---: | ---: | ---: |
| 1.5R baseline | -$5.55 | -$5.71 | 0.71 |
| 2.0R baseline | -$4.70 | -$6.22 | 0.71 |
| 1.5R, gap aligned | -$5.57 | -$4.52 | 0.76 |
| 1.5R, volume >= 1.2x | -$4.07 | -$10.81 | 0.56 |

Trend, volume, and combined filters did not repair the MES result.

### NQ, recent 60-day sample

The NQ dataset spans 2026-04-13 through 2026-06-18 and is too small for promotion.

| Variant | Development trades | Development expectancy | Holdout trades | Holdout expectancy | Holdout PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1.5R baseline | 19 | -$32.87 | 15 | +$16.70 | 1.32 |
| 2.0R baseline | 19 | -$22.29 | 15 | +$13.53 | 1.22 |
| 2.0R, gap aligned | 12 | -$4.04 | 8 | +$67.12 | 2.57 |

The positive recent holdout is a candidate, not a verified edge: development was
negative and the best holdout contains only eight trades.

## 2026-08-19 Diagnostic

- Opening gap: +0.37%.
- Opening-range low: 29,560.50.
- Completed downside breakout: 09:45 ET at 29,470.00.
- Direction: counter-gap.
- Maximum favorable excursion after the break: 94.25 NQ points.
- Qualified boundary retest: none.

The previous implementation could not see a delayed breakout. The new detector sees
the move, but correctly classifies it as `breakout_without_qualified_retest`. Entering
after the decline would be a chase and is not authorized by this sequence.

## Decision

Status: shadow only.

The sequence has no order authority. Promotion requires at least 30 independent
forward candidates across at least 20 trading dates, positive post-cost expectancy,
profit factor above 1.15, and no single date contributing more than 20% of profit.
Development/holdout disagreement must also be resolved before execution is considered.

