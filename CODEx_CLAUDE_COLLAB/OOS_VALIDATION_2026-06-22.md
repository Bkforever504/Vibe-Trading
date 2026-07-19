# Out-of-Sample Validation - 2026-06-22

## What Codex Added

- `ValidationSplitResult` in `strategies/topstep_replay_backtester.py`
- `split_train_test(candles, train_end)`
- `run_validation_split(...)`
- CLI flag: `--train-end YYYY-MM-DD`
- JSON validation output with train/test metrics and performance gaps
- Tests for inclusive train split and train/test expectancy gap

Verification:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
37 passed
```

## MNQ Pullback OOS Result

Dataset: `examples/nq_1h_730d.csv`

Unique trading dates: 597

Split:
- Train: 2024-01-29 through 2025-09-05, 400 dates
- Test: dates after 2025-09-05, 197 dates

Command:

```powershell
python strategies\topstep_replay_backtester.py --csv examples\nq_1h_730d.csv --symbol MNQ --range-minutes 1 --min-breakout-points 20.0 --reward-risk 2.0 --slippage-ticks 1 --commission 4.00 --signal-type pullback --pullback-stop-ticks 80 --pullback-tolerance-ticks 16 --train-end 2025-09-05
```

Train:
- Total P&L: `$1,088.50`
- Win rate: `56.0%`
- Profit factor: `2.46`
- Expectancy: `$43.54/trade`
- Max drawdown: `$199.50`
- Trades: `25`
- Consistency violations: `2`

Test:
- Total P&L: `$24.50`
- Win rate: `26.7%`
- Profit factor: `1.03`
- Expectancy: `$1.63/trade`
- Max drawdown: `$627.00`
- Trades: `15`
- Consistency violations: `7`

Performance gap:
- Expectancy gap: `-$41.91/trade`
- Win-rate gap: `-29.33 percentage points`
- Profit-factor gap: `-1.43`

Verdict:

MNQ first-pullback is not combine-ready. It remains slightly positive out of sample, but the edge degraded hard and rule violations increased. Keep this in paper/shadow mode.

Updated confidence:
- Compliance safety: `9.5/10`
- Backtester reliability: `8.5/10`
- Strategy profit confidence: `4.5/10`
- Forward-test confidence: `2.0/10`
- Combine-readiness: `1.5/10`

## MES / ES Comparison

Important correction: MES must use ES price data, not NQ price data. The old handoff command using `examples/nq_1h_730d.csv --symbol MES` is not valid for a real comparison.

Fetched ES data:

```powershell
uv run --no-project --with yfinance python scripts\fetch_nq_yfinance.py --ticker ES=F --interval 1h --period 730d --out examples\es_1h_730d.csv
```

Result: `3,559` bars across `598` trading days.

Same copied pullback config on ES/MES:

```powershell
python strategies\topstep_replay_backtester.py --csv examples\es_1h_730d.csv --symbol MES --range-minutes 1 --min-breakout-points 20.0 --reward-risk 2.0 --slippage-ticks 1 --commission 4.00 --signal-type pullback --pullback-stop-ticks 80 --pullback-tolerance-ticks 16 --train-end 2025-09-05
```

Train:
- Total P&L: `$230.00`
- Win rate: `80.0%`
- Profit factor: `2.93`
- Expectancy: `$46.00/trade`
- Max drawdown: `$119.00`
- Trades: `5`
- Consistency violations: `4`

Test:
- Total P&L: `$114.50`
- Win rate: `100.0%`
- Profit factor: `inf`
- Expectancy: `$57.25/trade`
- Max drawdown: `$0.00`
- Trades: `2`
- Consistency violations: `1`

Verdict:

MES/ES is too sparse with the copied NQ parameters. Seven trades across almost 600 trading days is not enough to trust. MES needs its own parameter sweep before it can be compared honestly.

## Next Best Work

1. Add a multi-timeframe trend filter for MNQ:
   - Only long when daily close is above daily 20 SMA.
   - Only short when daily close is below daily 20 SMA.
   - Goal: reduce test drawdown and consistency violations.

2. Run a train-only parameter sweep, then validate only the selected winner on test:
   - Avoid selecting parameters from full-period results.
   - Record train/test degradation for each candidate.

3. Add a consistency-aware objective:
   - Penalize configs where one day contributes more than 50% of cumulative profit.
   - Prefer lower expectancy with zero payout-rule violations over higher expectancy that cannot pass Topstep payout rules.

4. Build the forward-test viewer:
   - Read `~\.vibe-trading\shadow-ai-signals.jsonl`
   - Show unresolved, target-hit, stop-hit, and EOD outcomes.
   - After 30+ live paper signals, update confidence.
