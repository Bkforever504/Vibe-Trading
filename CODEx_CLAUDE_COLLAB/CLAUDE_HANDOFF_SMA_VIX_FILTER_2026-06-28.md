# Claude Handoff - SMA Momentum VIX Filter Test

Date: 2026-06-28

## What Codex Built

Updated:

```text
research/pine_strategy_lab/examples/sma_momentum_python.py
research/pine_strategy_sweep.py
scripts/strategy_sweep_runner.py
test_pine_strategy_sweep.py
```

New behavior:

- `sma_momentum_python.strategy()` accepts `vix_threshold`.
- If `vix_threshold` is set, the strategy requires `ohlcv["vix_close"]`.
- When `vix_close > threshold`, the strategy blocks new longs and flattens existing longs.
- Sweep runner supports `--include-vix`, which fetches `^VIX` and merges it into each OHLCV frame as `vix_close`.

## Verification

```powershell
uv run --no-project --with pytest --with pandas --with yfinance python -m pytest test_pine_strategy_sweep.py test_pine_strategy_lab.py -q
```

Result:

```text
33 passed
```

Sweep:

```powershell
uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\sma_momentum_python.py --symbols SPY,QQQ,IWM,GLD,TLT,XLK,XLF,XLE,XLV,EEM --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 --include-vix --pool-by-params --out research\pine_strategy_lab\sma_momentum_vix_pooled_sweep_report.md
```

## Result

The VIX filter did **not** fix the SMA momentum drawdown problem.

Best baseline row:

```text
sma_window=150 | PF 2.10 | OOS PF 5.12 | WF 0.60 | trades 188 | DD 37.5% | rejected
```

Best VIX row:

```text
sma_window=150, vix_threshold=30 | PF 1.73 | OOS PF 5.12 | WF 0.60 | trades 238 | DD 37.5% | rejected
```

Interpretation:

- VIX filter preserved breadth/sample size.
- It did not reduce max drawdown below the 25% gate.
- It reduced profit factor on the best row.
- Do not promote SMA momentum yet.

## Next Best Task

Implement ATR trailing stop variants in `sma_momentum_python.py`.

Candidate grid additions:

```python
{"sma_window": 150, "atr_window": 14, "atr_mult": 2.0}
{"sma_window": 150, "atr_window": 14, "atr_mult": 3.0}
{"sma_window": 150, "vix_threshold": 30, "atr_window": 14, "atr_mult": 2.0}
```

Goal:

```text
Keep pooled trade_count >= 30, PF > 1.5, OOS PF > 1.15, WF >= 0.60, PBO < 0.60, max_drawdown <= 25%.
```
