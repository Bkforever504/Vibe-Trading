# Claude Handoff - Pine Strategy Sweep Runner

Date: 2026-06-28

Project:

```text
C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
```

## What Codex Built

New sweep engine:

```text
research/pine_strategy_sweep.py
scripts/strategy_sweep_runner.py
test_pine_strategy_sweep.py
```

New research-only example strategy families:

```text
research/pine_strategy_lab/examples/ema_crossover_python.py
research/pine_strategy_lab/examples/orb_breakout_python.py
research/pine_strategy_lab/examples/rsi_mean_reversion_python.py
```

Docs updated:

```text
research/pine_strategy_lab/README.md
research/pine_strategy_lab/sweep_report.md
```

## Capability

The sweep runner tests translated strategy modules across:

- symbols, e.g. `SPY,QQQ,IWM`
- date windows, e.g. `2020-01-01:2024-12-31`
- parameter grids from `PARAM_GRID` or `parameter_grid()`

It returns sorted `SweepResult` rows containing:

- strategy name
- symbol
- date window
- params
- `BacktestMetrics`
- `CandidateEvaluation`

Sort order:

```text
confidence desc -> OOS PF desc -> PF desc -> max drawdown asc
```

## Run Commands

Tests:

```powershell
uv run --no-project --with pytest --with pandas --with yfinance python -m pytest test_pine_strategy_sweep.py test_pine_strategy_lab.py -q
```

Result:

```text
23 passed
```

Example sweep:

```powershell
uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\ema_crossover_python.py --symbols SPY --ranges 2022-01-01:2022-06-30 --out research\pine_strategy_lab\sweep_report.md
```

Result:

```text
Sweep rows: 3
All 3 EMA variants rejected with conf=0.3, PF=0.00, OOS=0.00, WF=0.00
```

This is good behavior: common indicator recipes should fail unless they prove OOS/walk-forward edge.

## Integration Rule

Do not wire sweep winners directly into `flip_bot.py`, `iwm_options_bot.py`, MNQ, Kalshi, or copy trader execution.

Route:

```text
sweep_report.md
-> red-flag review
-> paper/shadow module
-> 30+ forward-test signals
-> confidence >= 9/10
-> execution candidate
```

## Next Best Tasks

1. Run full sweeps:

```powershell
uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\ema_crossover_python.py --symbols SPY,QQQ,IWM --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 --out research\pine_strategy_lab\ema_sweep_report.md

uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\orb_breakout_python.py --symbols SPY,QQQ,IWM --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 --out research\pine_strategy_lab\orb_sweep_report.md

uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\rsi_mean_reversion_python.py --symbols SPY,QQQ,IWM --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 --out research\pine_strategy_lab\rsi_sweep_report.md
```

2. Add source attribution fields to sweep output:

```text
source_pine_path
source_url
license
target_bot
```

3. Add a combined leaderboard script that merges all `*_sweep_report.md` outputs into one ranked queue.

4. Only after that, create bot-specific shadow modules for any strategy family that survives.
