# TradingView Indicator Recipe Results

Date: 2026-07-25

## Verdict

No tested Killzone, Failed 2, pivot, Heikin-Ashi, VWAP, or HTF recipe earned
promotion to a bot, simulator, or scheduled shadow strategy.

The tests found no "perfect indicator recipe." More confluence consistently
reduced trade count without repairing expectancy. These tools can still be
useful chart context, but none supplied a profitable execution edge under the
fixed rules and realistic costs.

## Research Coverage

The research sweep included:

- Direct TradingView review of open-source Killzone/pivot and Failed 2 scripts.
- TradingView's official Heikin-Ashi and non-standard-chart backtest warnings.
- GitHub Pine Script collections and open-source strategy repositories.
- Direct YouTube searches for Killzone, pivot, Failed 2, VWAP, and
  Heikin-Ashi workflows.
- A `last30days` sweep across Reddit and Hacker News.

The last-30-days engine returned 17 Reddit threads and 5 Hacker News items.
Its X source failed, and YouTube was unavailable to that engine. A separate
repo X intake was blocked by the project's local spend guard because its
monthly request budget was already exhausted. No X call was forced and no
additional credit was spent.

The strongest recent social signal was methodological, not an indicator:
experienced-trader discussion emphasized trend-following versus mean
reversion, zones instead of exact lines, enough observations, and distrust of
unverified influencer P&L.

## Source Interpretation

### Killzones

Open-source TradingView scripts mark session windows, highs, lows, midpoints,
and opening references. Their own descriptions correctly treat those levels
as context rather than standalone entries. The tested New York AM window did
not improve Failed 2 expectancy.

### Failed 2

Two interpretations were preserved:

1. A preregistered three-bar Strat interpretation.
2. A second preregistered source-matched replication after direct inspection
   showed that the current TradingView script defines a strict Failed 2 as one
   candle that wicks through a level, closes back inside, and closes in the
   reversal direction.

The first result was not silently rewritten. Both interpretations failed.

### Pivot Points

Traditional P, R1, and S1 plus prior-day high/low were computed only from the
prior complete RTH session. Requiring a wick rejection at those locations did
not create positive expectancy.

### Heikin-Ashi

HA was calculated as a 15-minute trend-state filter. Every entry, stop,
target, and P&L value used real OHLC. This avoids the synthetic-fill error
TradingView warns about. HA occasionally improved a small SPY gross subset,
but it remained negative after costs, failed across time windows, and did not
transfer to MES.

## Experiment One: Three-Bar Interpretation

Complete sessions:

- MES: 1,108 of 1,148.
- SPY IEX: 411 of 1,137. The 2024 SPY coverage is particularly thin.

Aggregate results:

| Variant | MES trades | MES exp | MES PF | SPY trades | SPY exp | SPY PF |
|---|---:|---:|---:|---:|---:|---:|
| Raw | 1,104 | -0.1398R | 0.7948 | 409 | -0.2016R | 0.7158 |
| Killzone | 885 | -0.1607R | 0.7669 | 355 | -0.1885R | 0.7308 |
| Pivot | 504 | -0.1295R | 0.8037 | 176 | -0.2250R | 0.6800 |
| Pivot + Killzone | 151 | -0.2873R | 0.6110 | 55 | -0.1940R | 0.7245 |
| + HA | 40 | -0.2569R | 0.6405 | 18 | -0.0798R | 0.8701 |
| + VWAP | 105 | -0.3249R | 0.5665 | 36 | -0.1740R | 0.7444 |
| Full recipe | 22 | -0.2588R | 0.6354 | 12 | -0.1917R | 0.7069 |

The least-bad 2025+ result was MES raw at -0.0655R per trade. Its interval
still crossed zero, and it was negative in development and selection. The
full recipe produced only 6 MES and 7 SPY diagnostic trades.

## Experiment Two: Source-Matched Failed 2

Aggregate results:

| Variant | MES trades | MES exp | MES PF | SPY trades | SPY exp | SPY PF |
|---|---:|---:|---:|---:|---:|---:|
| All day | 949 | -0.3211R | 0.5904 | 306 | -0.0746R | 0.8865 |
| Killzone | 764 | -0.3039R | 0.6079 | 244 | -0.1325R | 0.8066 |
| Killzone + HA | 359 | -0.2524R | 0.6639 | 115 | -0.3090R | 0.5966 |
| Killzone + VWAP | 649 | -0.3185R | 0.5896 | 215 | -0.2498R | 0.6668 |
| Full recipe | 178 | -0.3184R | 0.5932 | 60 | -0.3984R | 0.5034 |

Source-matched MES Failed 2 was negative in every chronological window for
every variant. SPY all-day had positive gross expectancy but became negative
after ordinary two-sided costs, was negative in development and 2025+, and
had only seven 2024 trades.

All 24 market-by-variant promotion decisions across both experiments failed.

## What The Indicators Are Good For

| Tool | Defensible role | Execution verdict |
|---|---|---|
| Killzone/session boxes | Time normalization and session-level logging | Not a signal |
| PDH/PDL and floor pivots | Location and distance features | Not a signal |
| VWAP | Intraday state and execution benchmark | Existing context only |
| Heikin-Ashi | Smoothed HTF trend visualization | State only, never fill price |
| Failed 2 | A falsifiable rejection event | Rejected under tested rules |
| Open-source Pine repos | Hypothesis library and implementation reference | Audit before porting |

## The Best Recipe Now

The best recipe is a process, not an indicator stack:

1. Trade only a preregistered strategy family.
2. Define regime and location with point-in-time data.
3. Use one independently tested trigger.
4. Enter on the next executable real-price bar.
5. Deduct spread, slippage, commission, and reject gap-through-stop entries.
6. Test development, selection, consumed-later, double-cost, outlier removal,
   and forward evidence.
7. Promote only after the written gate passes.

For this project, the passing momentum rotation, turn-of-month, and PEAD lanes
remain better candidates than any indicator recipe tested here. Killzone,
pivot, HA, and Failed 2 fields may be logged as research context, but they
should not change Alpaca or Topstep execution.

## Open-Source References

- TradingView Failed 2 Evaluator:
  https://www.tradingview.com/script/Wa8a8Jp7-Failed-2-Evaluator-v2-2-Failed-2-Evaluator-Continuation-Engine/
- TradingView ICT Killzones & Pivots:
  https://www.tradingview.com/script/WZSxykp2-ICT-Killzones-Pivots-TFO/
- TradingView Heikin-Ashi warning:
  https://www.tradingview.com/support/solutions/43000481029-strategy-produces-unrealistic-results-on-non-standard-chart-types-heikin-ashi-renko-etc/
- hasnocool Pine strategy collection:
  https://github.com/hasnocool/tradingview-pine-scripts
- Alorse Pine strategy collection:
  https://github.com/Alorse/pinescript-strategies

These repositories contain hypotheses, not verified profitability. Licensing,
look-ahead, repainting, synthetic fills, costs, and symbol portability must be
audited before any code is reused.

## YouTube Hypothesis Sources

- TTrades, Killzone settings:
  https://youtube.com/watch?v=MPeeE55rNOw
- Dontez Akram, Failed 2 walkthrough:
  https://youtube.com/watch?v=rn5k6UojckY
- Tradeciety, pivot strategy:
  https://youtube.com/watch?v=MEFws0iLTMA

These were used to understand terminology and candidate mechanics. Marketing
claims and displayed win rates were not accepted as evidence.

## Artifacts

- `research/indicator_recipe_lab.py`
- `research/failed2_source_matched_lab.py`
- `data/indicator_recipe_results.json`
- `data/failed2_source_matched_results.json`
- `agent/tests/test_indicator_recipe_lab.py`
- `agent/tests/test_failed2_source_matched_lab.py`

No production bot, live configuration, scheduler, order route, or risk gate
was changed.
