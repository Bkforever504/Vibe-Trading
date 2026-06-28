# Claude Handoff - SMA Rotation Tiered GLD Evaluation

Date: 2026-06-28

## What Codex Evaluated

User asked Codex to choose between:

1. Narrowing the ETF basket.
2. Adding tiered rotation: equity -> GLD -> cash when GLD is below its own SMA.

Codex did both in sequence.

## Existing Work Found

Claude had already added:

```text
research/pine_strategy_lab/examples/sma_rotation_python.py
research/pine_strategy_lab/sma_rotation_gld_report.md
research/pine_strategy_lab/sma_rotation_tlt_report.md
```

Codex preserved this work and built on it.

## Fixes / Infrastructure

Updated:

```text
research/pine_strategy_lab_backtest.py
research/pine_strategy_sweep.py
scripts/strategy_sweep_runner.py
test_pine_strategy_sweep.py
```

New capability:

```text
--defensive-sma-window 150
```

This creates tiered rotation:

```text
equity above SMA -> long equity
equity below SMA and GLD above GLD SMA -> long GLD
equity below SMA and GLD below GLD SMA -> cash
```

## Reports Generated

```text
research/pine_strategy_lab/sma_rotation_gld_narrow_report.md
research/pine_strategy_lab/sma_rotation_gld_tiered_report.md
research/pine_strategy_lab/sma_rotation_gld_tiered_narrow_report.md
research/pine_strategy_lab/sma_rotation_gld_tiered_narrow_long_report.md
research/pine_strategy_lab/sma_rotation_gld_tiered_core_report.md
```

## Verification

```powershell
uv run --no-project --with pytest --with pandas --with yfinance python -m pytest test_pine_strategy_sweep.py test_pine_strategy_lab.py -q
```

Result:

```text
34 passed
```

## Key Results

### Narrow basket, GLD rotation

Basket:

```text
SPY, QQQ, IWM, XLK, XLV
```

Top row:

```text
2020-2024, sma_window=180
PF 3.10
OOS PF 99.00
WF 0.76
Trades 78
Max DD 34.6%
Status: rejected
```

Narrowing alone did not solve drawdown or suspicious OOS.

### Tiered GLD rotation, narrow basket

Command:

```powershell
uv run --no-project --with pandas --with yfinance python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\sma_rotation_python.py --symbols SPY,QQQ,IWM,XLK,XLV --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31 --defensive GLD --defensive-sma-window 150 --pool-by-params --out research\pine_strategy_lab\sma_rotation_gld_tiered_narrow_report.md
```

Top row:

```text
2020-2024, sma_window=180
PF 3.28
OOS PF 99.00
WF 0.76
Trades 78
Max DD 22.7%
Confidence 8.0
Status: rejected
```

This fixed drawdown, but OOS PF 99.00 is still suspicious and correctly rejects.

### Tiered GLD rotation, core basket

Basket:

```text
SPY, QQQ, XLK, XLV
```

Top clean-ish row:

```text
2018-2024, sma_window=150
PF 2.41
OOS PF 3.36
WF 0.65
Trades 96
Max DD 28.7%
Confidence 7.6
Status: rejected
```

This removes suspicious OOS but fails the 25% drawdown gate.

## Honest Verdict

No paper candidate yet.

Tiered GLD rotation is the best structural improvement so far:

- It can reduce DD below 25% on 2020-2024 narrow basket.
- It improves confidence to 8.0.
- But the best low-DD row has suspicious OOS PF 99.00.
- Longer windows remove OOS weirdness but DD rises above 25%.

Do not promote to bot integration.

## Next Best Path

Try a combined report that explicitly separates:

1. full 2018-2024
2. COVID crash window
3. 2022 bear window
4. post-2022 recovery

If the strategy only fails one window, we can decide whether it needs a regime-specific guard. If it fails multiple windows, park SMA rotation and move to another strategy family.
