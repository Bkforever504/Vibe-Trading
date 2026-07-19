# SMC Key-Level Layer - 2026-06-22

## What Codex Built

This adds the first testable SMC/key-level layer without connecting live orders.

Files changed:
- `strategies/topstep_replay_backtester.py`
- `strategies/topstep_prop_bot.py`
- `agent/tests/test_topstep_replay_backtester.py`
- `agent/tests/test_topstep_prop_bot.py`

## Features

### Prior-Day Levels

Added:
- `build_prior_day_levels(candles)`

For each trading date, it returns the previous completed day's:
- High
- Low
- Close

The first day returns `None`. This avoids lookahead.

### Key-Level Proximity Filter

Added config:
- `require_key_level_proximity`
- `key_level_tolerance_ticks`

Added CLI:
- `--require-key-level-proximity`
- `--key-level-tolerance-ticks`

Behavior:
- A signal must enter near the prior-day high, prior-day low, or prior-day close.
- The opening-range level itself is not counted as a key level, because every pullback already touches it and that would make the filter meaningless.

### Break-of-Structure Confirmation

Added config:
- `require_bos_confirm`

Added CLI:
- `--require-bos-confirm`

Behavior:
- Long pullback requires a higher high after the breakout candle before pullback entry.
- Short pullback requires a lower low after the breakout candle before pullback entry.
- BOS must happen before the pullback candle, not on the same candle.

This is intentionally strict. It is probably more useful on 1m/5m bars than on the current 1h data.

## Verification

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
52 passed
```

## OOS Results

Dataset:
`examples/nq_1h_730d.csv`

Split:
- Train through `2025-09-05`
- Test after `2025-09-05`

Base config:

```powershell
--signal-type pullback
--range-minutes 1
--min-breakout-points 20.0
--reward-risk 2.0
--pullback-stop-ticks 80
--pullback-tolerance-ticks 16
--require-opening-gap-bias
--min-opening-gap-pct 0
--consistency-penalty 100
```

Comparison:

| Mode | Test P&L | WR | PF | Exp/trade | DD | Trades | Violations | Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Gap bias only | `$425.00` | `50.0%` | `2.99` | `$70.83` | `$132.50` | `6` | `3` | `-229.17` |
| Gap + key levels, 16 ticks | `-$132.50` | `0.0%` | `0.00` | `-$132.50` | `$132.50` | `1` | `0` | `-132.50` |
| Gap + key levels, 24-120 ticks | `$25.00` | `50.0%` | `1.19` | `$12.50` | `$132.50` | `2` | `0` | `$12.50` |
| Gap + BOS | `$0.00` | `0.0%` | `0.00` | `$0.00` | `$0.00` | `0` | `0` | `$0.00` |
| Gap + key levels + BOS | `$0.00` | `0.0%` | `0.00` | `$0.00` | `$0.00` | `0` | `0` | `$0.00` |

## Verdict

Key-level proximity is useful as a safety filter:
- It removes all consistency violations in the OOS test.
- It preserves a small positive result at 24+ tick tolerance.
- It only leaves 2 test trades, so confidence is still low.

BOS is too strict on the current 1-hour dataset:
- It removes every OOS trade.
- This does not mean BOS is bad.
- It means 1-hour bars are too coarse for BOS/pullback sequencing.

Updated confidence:
- Backtester reliability: `9.2/10`
- SMC filter implementation confidence: `8.5/10`
- Strategy profit confidence: `5.1/10`
- Combine-readiness: `2.8/10`

## Next Best Work

Claude can help with either of these:

1. Build a 5m-data path:
   - Fetch 5m NQ and ES history.
   - Run the same gap + key-level + BOS filters on 5m.
   - Avoid making conclusions about BOS on 1h candles.

2. Build partial/breakeven exit model:
   - Partial at 1R.
   - Move remaining stop to breakeven.
   - Runner exits at 2R or EOD.
   - Compare against full-position target/stop.

3. Add premarket levels once 1m/5m data is available:
   - Premarket high
   - Premarket low
   - Current RTH open gap vs prior close

Do not connect live orders. Paper/replay only.
