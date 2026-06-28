# Claude Handoff - Momentum Rotation Top-N Candidate

Date: 2026-06-28
Owner: Codex
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Decision

Proceed with the **expanded-universe weekly momentum rotation, 12-month lookback, top-2 equal-weight** as a research-only paper candidate.

Do **not** wire this to live execution. Next step is paper/shadow tracking and a second independent validation pass.

## Candidate

Command:

```powershell
uv run --no-project --with pandas --with yfinance python scripts\momentum_sweep_runner.py --symbols SPY,QQQ,GLD,XLE,TLT,IWM,XLK,XLV,XLF,XLI --lookbacks 3 6 12 --top-n 1 2 3 --ranges 2018-01-01:2024-12-31 --rebalance-days 5 --out research\momentum_rotation\weekly_expanded_topn_report.md
```

Winning row:

| Metric | Value |
|---|---:|
| Universe | SPY, QQQ, GLD, XLE, TLT, IWM, XLK, XLV, XLF, XLI |
| Rebalance | Weekly / 5 trading days |
| Lookback | 12 months |
| Holdings | Top 2 positive-momentum assets, equal-weight |
| Status | paper_candidate |
| Confidence | 9.0 |
| PF | 1.92 |
| OOS PF | 1.79 |
| Walk-forward | 0.80 |
| Sharpe | 0.79 |
| Win rate | 64.5% |
| Trades | 76 |
| Max DD | 24.3% |
| PBO | 0.25 |

## What Changed

- `research/momentum_rotation_backtest.py`
  - `top_n` now works as a true equal-weight basket.
  - Cash filter still applies: if all ranked assets have negative momentum, hold cash.
  - Trade returns count uninterrupted basket-holding periods.
- `scripts/momentum_sweep_runner.py`
  - Added `--top-n` sweep parameter.
  - Report params now include both `lookback_months` and `top_n`.
- `test_momentum_rotation_backtest.py`
  - Added focused tests for top-N selection, cash filter, equal-weight returns, basket trade counting, and time-in-market.

## Validation

```powershell
uv run --no-project --with pytest --with pandas --with numpy python -m pytest test_momentum_rotation_backtest.py test_pine_strategy_lab.py test_pine_strategy_lab_backtest.py test_pine_strategy_sweep.py -q
```

Result: `50 passed`.

## Rejected Variants

Original six-asset weekly/top-N report:

`research\momentum_rotation\weekly_6_topn_report.md`

Best six-asset row missed by drawdown only:

- 12m / top-3: PF 1.86, OOS PF 1.77, WF 1.00, trades 102, DD 25.6%, PBO 0.50, confidence 8.2.

Expanded universe, top-1 missed by drawdown/trade count:

- 12m / top-1: PF 5.60, OOS PF 2.06, WF 0.80, trades 27, DD 26.0%.

## Next Recommended Work

1. Add a paper/shadow signal generator that logs weekly target holdings only, with no Alpaca orders.
2. Add a “rebalance explanation” report: prior holdings, new ranks, 12m returns, cash-filter state.
3. Validate on a second date window, ideally 2015-2024 if data downloads cleanly.
4. Only after 30-60 days of forward logs, consider small paper execution through guarded Alpaca fractional ETF orders.
