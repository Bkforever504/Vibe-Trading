# Gap Bias + Tight Stop Experiment - 2026-06-22

## Question

Kenny asked whether Claude's suggestion was useful:

1. Add a free-data regime filter using premarket/opening bias.
2. Sweep tighter pullback stops from 8 to 24 ticks.

## Verdict

Useful, but not enough to make the strategy combine-ready.

The opening-gap bias is worth keeping because it improved the OOS test set. The tight-stop experiment is directionally useful, but results are limited by the current 1-hour dataset. Profitable MNQ traders use 1m/5m structure for 8-15 tick stops. A 1-hour candle hides the wick/rejection detail that would make tight stops meaningful.

## What Codex Implemented

File: `strategies/topstep_replay_backtester.py`

Added:
- `BacktestConfig.require_opening_gap_bias`
- `BacktestConfig.min_opening_gap_pct`
- `build_opening_gap_sides(candles, min_gap_pct)`
- CLI flags:
  - `--require-opening-gap-bias`
  - `--min-opening-gap-pct`

Because the current historical CSV is RTH-only, this is implemented as:

```text
current first RTH open vs prior completed RTH close
```

Later, this can be upgraded to true QQQ/SPY premarket gap data when we have reliable 1m/5m history.

Tests added:
- Opening gap side map uses prior close to current open.
- Gap-down day blocks long signal.
- Gap-up day allows long signal.

Verification:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
47 passed
```

## OOS Gap Bias Results

Dataset: `examples/nq_1h_730d.csv`

Split:
- Train through `2025-09-05`
- Test after `2025-09-05`

Base pullback config:

```powershell
--signal-type pullback
--range-minutes 1
--min-breakout-points 20.0
--reward-risk 2.0
--pullback-stop-ticks 80
--pullback-tolerance-ticks 16
--consistency-penalty 100
```

OOS comparison:

| Mode | Test P&L | WR | PF | Exp/trade | DD | Trades | Violations | Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Daily trend only | `$24.00` | `25.0%` | `1.09` | `$3.00` | `$156.00` | `8` | `3` | `-297.00` |
| Gap bias, 0% threshold | `$425.00` | `50.0%` | `2.99` | `$70.83` | `$132.50` | `6` | `3` | `-229.17` |
| Gap bias, 0.3% threshold | `$368.00` | `37.5%` | `2.36` | `$46.00` | `$156.00` | `8` | `4` | `-354.00` |
| Daily trend + gap bias, 0% threshold | `$85.50` | `40.0%` | `1.40` | `$17.10` | `$132.50` | `5` | `2` | `-182.90` |
| Daily trend + gap bias, 0.3% threshold | `$28.50` | `28.6%` | `1.11` | `$4.07` | `$156.00` | `7` | `3` | `-295.93` |

Best current risk-adjusted OOS variant:

```powershell
python strategies\topstep_replay_backtester.py --csv examples\nq_1h_730d.csv --symbol MNQ --range-minutes 1 --min-breakout-points 20.0 --reward-risk 2.0 --slippage-ticks 1 --commission 4.00 --signal-type pullback --pullback-stop-ticks 80 --pullback-tolerance-ticks 16 --train-end 2025-09-05 --require-daily-trend-confirm --daily-trend-sma-days 20 --require-opening-gap-bias --min-opening-gap-pct 0 --consistency-penalty 100
```

This still is not combine-ready because the consistency-adjusted score remains negative.

## Tight Stop Sweep

Stops tested:

```text
8, 12, 16, 20, 24, 32, 40, 60, 80 ticks
```

Best by consistency-adjusted score:

| Mode | Stop ticks | Test P&L | Exp/trade | PF | WR | DD | Trades | Violations | Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Trend + gap | 40 | `-$113.50` | `-$22.70` | `0.51` | `20.0%` | `$190.50` | `5` | `0` | `-22.70` |
| Trend + gap | 8 | `-$95.50` | `-$23.88` | `0.47` | `25.0%` | `$138.00` | `4` | `0` | `-23.88` |
| Gap only | 8 | `$172.00` | `$34.40` | `1.95` | `40.0%` | `$138.00` | `5` | `1` | `-65.60` |
| Gap only | 40 | `$186.00` | `$31.00` | `1.81` | `33.3%` | `$190.50` | `6` | `1` | `-69.00` |
| Trend + gap | 80 | `$85.50` | `$17.10` | `1.40` | `40.0%` | `$132.50` | `5` | `2` | `-182.90` |

Interpretation:

- Gap-only tight stops are interesting but still violate consistency.
- Trend+gap tight stops reduce violations but lose money.
- On 1-hour bars, 8-24 tick stops are not trustworthy. Need 1m/5m historical data before deciding whether tight stops are real edge.

## Updated Confidence

- Backtester reliability: `9.0/10`
- Gap-bias filter usefulness: `6.5/10`
- Tight-stop result confidence on 1h data: `3.0/10`
- Strategy profit confidence: `5.0/10`
- Combine-readiness: `2.5/10`

## Next Best Work

1. Do not replace the current baseline with tight stops yet.
2. Keep opening-gap bias available for sweeps.
3. Get 1m/5m historical futures data before making conclusions about 8-24 tick stops.
4. Build SMC/key-level filters next:
   - Prior day high/low
   - Premarket high/low
   - Break of structure
   - Order-block pullback zone
   - Partial at 1R and stop-to-breakeven model
