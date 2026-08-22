# Source-Matched Failed 2 Replication Preregistration

Date frozen: 2026-07-25

## Why This Separate Experiment Exists

Direct inspection of the open-source TradingView `Failed 2 Evaluator v2.2`
after the first indicator-recipe run showed that its published trigger differs
from the first lab's three-bar Strat interpretation.

The first result remains unchanged and is labeled `three_bar_interpretation`.
This separate experiment matches the public script description:

- an active level is physically breached by a candle wick;
- the same candle closes back inside the level; and
- the same candle closes in the reversal direction relative to its own open.

## Fixed Levels And Execution

- Active levels: prior-day high, prior-day low, traditional pivot P, R1, S1.
- Maximum excursion beyond a level: 5% of prior-day RTH range.
- Bars: real-price five-minute OHLCV.
- Entry: next five-minute bar open.
- Stop: one tick beyond the Failed 2 candle extreme.
- Target: 1.5R.
- Same-bar ambiguity: stop first.
- One trade maximum per variant per session.
- Risk must be at least two ticks and no more than 25% of prior RTH range.

## Fixed Variants

1. `level_failed2_all_day`
2. `level_failed2_killzone`
3. `level_failed2_killzone_ha`
4. `level_failed2_killzone_vwap`
5. `level_failed2_full`

The killzone, 15-minute Heikin-Ashi state, real-price VWAP, HTF non-opposition,
costs, chronological windows, metrics, and promotion gates are identical to
the parent indicator-recipe preregistration.

No thresholds or variants may be changed after this result is produced.
