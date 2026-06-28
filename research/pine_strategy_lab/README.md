# Pine Strategy Lab

Purpose:

```text
Turn legal/open-source TradingView Pine strategy ideas into a ranked research queue.
```

This is not a live-trading shortcut. It is a filter that rejects hype backtests before they can touch the bots.

## Workflow

1. Save only legal/open-source Pine strategies as `.pine` files.
2. Convert or manually port the logic into Python for honest backtesting.
3. Backtest with slippage, fees, realistic fills, trade-level metrics, out-of-sample windows, and walk-forward splits.
4. Put the resulting metrics in a manifest.
5. Generate a candidate report.
6. Promote only `paper_candidate` strategies into shadow/paper-forward testing.

## Manifest Format

```json
[
  {
    "pine_file": "examples/vwap_candidate.pine",
    "metrics": {
      "total_return_pct": 41.5,
      "profit_factor": 1.65,
      "max_drawdown_pct": 8.2,
      "trade_count": 88,
      "out_of_sample_profit_factor": 1.22,
      "walk_forward_pass_rate": 0.66,
      "avg_win_pct": 1.4,
      "avg_loss_pct": -0.9,
      "expectancy_pct": 0.28,
      "max_consecutive_losses": 3,
      "time_in_market_pct": 42.5
    }
  }
]
```

Run:

```powershell
uv run --no-project python scripts\pine_strategy_lab_report.py --manifest research\pine_strategy_lab\manifest.json
```

## Strategy Sweeps

Use the sweep runner before promoting any translated strategy family into a bot-specific shadow module.

```powershell
uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py `
  --strategy research\pine_strategy_lab\examples\ema_crossover_python.py `
  --symbols SPY,QQQ,IWM `
  --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 `
  --out research\pine_strategy_lab\sweep_report.md
```

Supported strategy modules can expose either:

```python
PARAM_GRID = [{"fast": 9, "slow": 21}, {"fast": 20, "slow": 50}]
```

or:

```python
def parameter_grid() -> list[dict]:
    return [{"lookback": 10}, {"lookback": 20}]
```

The runner sorts by confidence, OOS profit factor, profit factor, then drawdown. Sweep winners are research candidates only; they still need red-flag review and 30+ forward-test signals before bot integration.

For daily strategies that do not trade often enough per instrument, use pooled-universe evaluation:

```powershell
uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py `
  --strategy research\pine_strategy_lab\examples\sma_momentum_python.py `
  --symbols SPY,QQQ,IWM,GLD,TLT,XLK,XLF,XLE,XLV,EEM `
  --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 `
  --pool-by-params `
  --out research\pine_strategy_lab\sma_momentum_pooled_sweep_report.md
```

Pooling groups rows by parameter set and date window, combines trade counts across symbols, and evaluates the basket as one research candidate. This is appropriate for daily mean-reversion or momentum systems where one ticker cannot produce enough completed trades alone.

Each sweep report includes a population-level PBO score:

```text
PBO score: 0.44 (0.00=stable, 1.00=likely overfit)
```

PBO is estimated from rank inversion across the sweep population: if the best in-sample parameter rows fall into the bottom half out-of-sample, the score rises. A score at or above `0.60` rejects the family/rows before bot integration.

## Rejection Gates

The first-pass gates reject:

- unknown or non-open-source license
- fewer than 30 trades
- suspiciously high profit factor above 10
- max drawdown above 25%
- out-of-sample profit factor below 1.15
- walk-forward pass rate below 60%
- PBO score at or above 0.60

## Backtest Metric Standard

The Python backtester uses completed-trade P&L for:

- profit factor
- trade count
- average win
- average loss
- expectancy
- max consecutive losses

It also reports time in market from the shifted position series. Bar-by-bar equity returns are still used for total return and drawdown, but they no longer define profit factor.

## Promotion Rule

`paper_candidate` does not mean trade live.

It means:

```text
Allowed into shadow/paper-forward testing only.
```

Live execution still requires:

- paper validation
- forward-test results
- rule compliance
- execution guard approval
- confidence score near 9/10
