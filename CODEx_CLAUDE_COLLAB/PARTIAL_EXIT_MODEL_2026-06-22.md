# Partial Exit Model - 2026-06-22

## Decision

Kenny asked Codex to choose the next free path after Claude's 5m replay verdict.

Choice:
- Build the partial-exit model now.
- Keep waiting on paid 1m/5m data for real BOS validation.

Reason:
- The 5m architecture works, but yfinance only gives 48 trading days and 4 trades per config.
- That is too small for confidence.
- Partial exits can be tested immediately on the existing data without spending money.

## What Codex Built

File:
`strategies/topstep_replay_backtester.py`

Added:
- `BacktestConfig.exit_model`
- CLI flag: `--exit-model`

Supported models:
- `full_target_stop` - original default
- `partial_1r_be_2r` - half exits at 1R, runner stop moves to breakeven, runner targets 2R or exits EOD

Exit reasons added:
- `partial_breakeven`
- `partial_target`
- `partial_eod`

Tests added:
- Half at 1R, runner stopped at breakeven.
- Half at 1R, runner reaches 2R.

Verification:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
54 passed
```

## OOS Comparison

Dataset:
`examples/nq_1h_730d.csv`

Split:
- Train through `2025-09-05`
- Test after `2025-09-05`

Base strategy:

```powershell
--signal-type pullback
--range-minutes 1
--min-breakout-points 20.0
--reward-risk 2.0
--pullback-stop-ticks 80
--pullback-tolerance-ticks 16
--consistency-penalty 100
```

Results:

| Mode | Test P&L | WR | PF | Exp/trade | DD | Trades | Violations | Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Gap only, full exit | `$425.00` | `50.0%` | `2.99` | `$70.83` | `$132.50` | `6` | `3` | `-229.17` |
| Gap only, partial exit | `$167.25` | `66.7%` | `1.97` | `$27.87` | `$132.50` | `6` | `2` | `-172.13` |
| Gap + key 24, full exit | `$25.00` | `50.0%` | `1.19` | `$12.50` | `$132.50` | `2` | `0` | `$12.50` |
| Gap + key 24, partial exit | `-$14.25` | `50.0%` | `0.89` | `-$7.12` | `$132.50` | `2` | `0` | `-$7.12` |
| Trend + gap, full exit | `$85.50` | `40.0%` | `1.40` | `$17.10` | `$132.50` | `5` | `2` | `-182.90` |
| Trend + gap, partial exit | `$85.00` | `60.0%` | `1.49` | `$17.00` | `$132.50` | `5` | `2` | `-183.00` |

## Verdict

Partial exits are useful to keep as a sweep option, but they should not become the default yet.

What improved:
- Gap-only win rate improved from `50.0%` to `66.7%`.
- Gap-only consistency violations dropped from `3` to `2`.
- Trend + gap win rate improved from `40.0%` to `60.0%`.

What got worse:
- Gap-only expectancy dropped from `$70.83/trade` to `$27.87/trade`.
- Gap + key-level positive result turned negative.
- Max drawdown did not improve on this 1h dataset.

Current best paper candidate remains:

```powershell
python strategies\topstep_replay_backtester.py --csv examples\nq_1h_730d.csv --symbol MNQ --range-minutes 1 --min-breakout-points 20.0 --reward-risk 2.0 --slippage-ticks 1 --commission 4.00 --signal-type pullback --pullback-stop-ticks 80 --pullback-tolerance-ticks 16 --train-end 2025-09-05 --require-opening-gap-bias --min-opening-gap-pct 0 --require-key-level-proximity --key-level-tolerance-ticks 24 --consistency-penalty 100
```

But confidence remains low because it only had 2 OOS trades.

Updated confidence:
- Backtester reliability: `9.3/10`
- Exit-model implementation confidence: `8.8/10`
- Strategy profit confidence: `5.1/10`
- Combine-readiness: `2.8/10`

## Need Claude?

Claude is useful for the next task, not this one.

Recommended Claude task:
- Build a train-only sweep harness that ranks configs by `consistency_adjusted_score`.
- Include these dimensions:
  - exit model
  - opening gap bias
  - key-level proximity tolerance
  - pullback stop ticks
  - BOS on/off
  - 5m vs 1h data

Alternative Claude task:
- Document exact Polygon.io data requirements and expected schema so we can plug paid 1m data into the current backtester without rewriting strategy logic.
