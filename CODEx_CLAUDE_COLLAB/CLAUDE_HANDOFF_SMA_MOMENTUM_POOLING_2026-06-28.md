# Claude Handoff - SMA Momentum + Pooled Universe Sweep

Date: 2026-06-28

## What Codex Built

New research-only strategy:

```text
research/pine_strategy_lab/examples/sma_momentum_python.py
```

Rule:

```text
long when close > SMA, cash when close <= SMA
```

Parameter grid:

```python
150, 180, 200, 220 day SMA
```

New pooled-universe infrastructure:

```text
research/pine_strategy_sweep.py::pool_sweep_results_by_params()
scripts/strategy_sweep_runner.py --pool-by-params
```

Why this matters:

Daily strategies often fail the 30-trade gate per ticker. Pooled evaluation combines trade counts across a basket for the same parameter set/date window, which is the right structure for daily ETF mean-reversion and momentum research.

## Verification

Tests:

```powershell
uv run --no-project --with pytest --with pandas --with yfinance python -m pytest test_pine_strategy_lab.py test_pine_strategy_sweep.py -q
```

Result:

```text
31 passed
```

Sweep:

```powershell
uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\sma_momentum_python.py --symbols SPY,QQQ,IWM,GLD,TLT,XLK,XLF,XLE,XLV,EEM --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 --pool-by-params --out research\pine_strategy_lab\sma_momentum_pooled_sweep_report.md
```

Top row:

```text
sma_window=150 | POOL[10] | 2020-2024 | 188 trades | PF 2.10 | OOS PF 5.12 | WF 0.60 | Max DD 37.5% | rejected
```

Interpretation:

- Pooling solved the sample-size problem.
- The top candidate still fails because max drawdown exceeds 25%.
- Do not promote SMA momentum into a bot yet.

## Next Best Task

Add volatility/risk overlays to SMA momentum research:

1. ATR stop or trailing stop variant.
2. Volatility targeting / max drawdown guard.
3. Market regime filter, e.g. trade only when VIX below threshold.
4. Re-run pooled sweep.

Promotion path remains:

```text
sweep report -> zero critical red flags -> paper/shadow module -> 30+ forward signals -> confidence >= 9/10 -> execution candidate
```
