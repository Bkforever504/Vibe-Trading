# Trend Filter + Consistency Objective - 2026-06-22

## Source Request

Kenny provided research saying the best 2026 MNQ prop-firm variants are not raw ORB. They are ORB + VWAP + structural pullback + strict time window + consistency-aware selection. The attached note specifically called for:

- Daily 20-SMA trend filter
- Consistency-rule penalty in the parameter-selection objective
- Continued ultra-selective paper/shadow mode

## What Codex Implemented

File: `strategies/topstep_replay_backtester.py`

Added:
- `BacktestConfig.require_daily_trend_confirm`
- `BacktestConfig.daily_trend_sma_days`
- `BacktestConfig.consistency_penalty_per_violation`
- `build_daily_trend_sides(candles, sma_days=20)`
- `consistency_adjusted_score(result, penalty_per_violation=...)`
- `allowed_side` gate inside `replay_day(...)`
- JSON summary field: `consistency_adjusted_score`
- CLI flags:
  - `--require-daily-trend-confirm`
  - `--daily-trend-sma-days`
  - `--consistency-penalty`

Tests added in `agent/tests/test_topstep_replay_backtester.py`:
- Daily trend uses prior completed closes only
- Daily trend blocks long signals below prior SMA
- Daily trend allows long signals above prior SMA
- Consistency-adjusted score penalizes rule violations even when raw expectancy is higher

Verification:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
41 passed
```

Compile check:

```powershell
python -m py_compile strategies\topstep_replay_backtester.py strategies\topstep_prop_bot.py strategies\prop_rule_gate.py strategies\risk_kill_switch.py strategies\shadow_pullback_signal.py
```

Result: clean.

## MNQ OOS Comparison

Dataset: `examples/nq_1h_730d.csv`

Train/test split:
- Train through `2025-09-05`
- Test after `2025-09-05`

### Current Pullback Config, No Daily Trend Filter

Command:

```powershell
python strategies\topstep_replay_backtester.py --csv examples\nq_1h_730d.csv --symbol MNQ --range-minutes 1 --min-breakout-points 20.0 --reward-risk 2.0 --slippage-ticks 1 --commission 4.00 --signal-type pullback --pullback-stop-ticks 80 --pullback-tolerance-ticks 16 --train-end 2025-09-05 --consistency-penalty 100
```

Test result:
- Total P&L: `$24.50`
- Win rate: `26.7%`
- Profit factor: `1.03`
- Expectancy: `$1.63/trade`
- Max drawdown: `$627.00`
- Trades: `15`
- Consistency violations: `7`
- Consistency-adjusted score: `-698.37`

### Same Config With Daily 20-SMA Trend Filter

Command:

```powershell
python strategies\topstep_replay_backtester.py --csv examples\nq_1h_730d.csv --symbol MNQ --range-minutes 1 --min-breakout-points 20.0 --reward-risk 2.0 --slippage-ticks 1 --commission 4.00 --signal-type pullback --pullback-stop-ticks 80 --pullback-tolerance-ticks 16 --train-end 2025-09-05 --require-daily-trend-confirm --daily-trend-sma-days 20 --consistency-penalty 100
```

Test result:
- Total P&L: `$24.00`
- Win rate: `25.0%`
- Profit factor: `1.09`
- Expectancy: `$3.00/trade`
- Max drawdown: `$156.00`
- Trades: `8`
- Consistency violations: `3`
- Consistency-adjusted score: `-297.00`

## Verdict

The daily trend filter improved risk quality but did not create a strong enough edge:

- Test drawdown improved from `$627.00` to `$156.00`
- Test consistency violations improved from `7` to `3`
- Test trades dropped from `15` to `8`
- Test expectancy stayed very small: `$3.00/trade`

This is better risk hygiene, not combine readiness.

Updated confidence:
- Compliance safety: `9.5/10`
- Backtester reliability: `8.8/10`
- Strategy profit confidence: `4.8/10`
- Forward-test confidence: `2.2/10`
- Combine-readiness: `2.0/10`

## Next Best Work

1. Build a real train-only parameter sweep that sorts by `consistency_adjusted_score`, not raw expectancy.
2. Test tighter entry windows:
   - 10:00-12:00 ET
   - 10:00-13:00 ET
   - 10:30-12:30 ET
3. Add SMC-style structure checks:
   - Break of structure
   - Pullback to order-block candle body
   - Reject entries far from VWAP
4. Keep scanner paper/shadow only until out-of-sample profit confidence is at least `7/10`.
