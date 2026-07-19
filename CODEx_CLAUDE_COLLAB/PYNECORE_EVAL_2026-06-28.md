# PyneCore P2 Evaluation

Date: 2026-06-28
Verdict: **SKIP for backtesting. Monitor for live signal path.**

---

## What Was Tested

Install: `pynesys-pynecore @ git+https://github.com/PyneSys/pynecore`
Status: installs cleanly, no PyPI package (GitHub only)

Explored: `pynecore.lib`, `pynecore.providers`, `pynecore.standalone`

---

## Findings

### 1. Data model — fundamental mismatch

PyneCore is NOT a backtesting library against pandas DataFrames.
It is a **bar-by-bar live execution runtime** with two built-in data providers:
- `CCXTProvider` — crypto exchanges via CCXT
- `CapitalComProvider` — CFD broker

There is no pandas DataFrame provider. No path to feed our existing
`yfinance` OHLCV data without writing a custom provider adapter.

Our contract: `StrategyFn(pd.DataFrame) -> pd.Series`
PyneCore contract: `@pyne-decorated function + Provider → bar events`

These are incompatible without significant wrapper work.

### 2. Execution model — import hook + decorators

PyneCore uses a Python import hook that transforms `@pyne`-decorated
functions to run bar-by-bar. This is architecturally sound for
repaint prevention (no future data access possible), but it is a
different paradigm entirely from our vectorized backtester.

### 3. PyneSys converter — still potentially useful, separately

PyneSys converts Pine Script → PyneCore Python via deterministic AST.
The output is PyneCore-style code, NOT our `StrategyFn` contract.

To use PyneSys output in our pipeline, we would need:
1. PyneSys convert Pine → PyneCore Python (Discord bot, free 3 scripts)
2. Write a shim that wraps PyneCore's bar-by-bar execution into our
   `StrategyFn(pd.DataFrame) -> pd.Series` contract
3. Test that shim against our manual translations

This is medium complexity — not a one-session task.

---

## Decision

| Requirement | Status |
|---|---|
| No lookahead in execution model | PASS — import hook enforces bar-by-bar |
| Handles commission/slippage | UNKNOWN — not tested (no pandas path) |
| Reproducible vs manual translation | UNTESTABLE — no pandas provider |

**Do NOT integrate PyneCore into the backtest pipeline.**

Reasons:
- No pandas DataFrame support → can't use our OHLCV data
- Our vectorized backtester already enforces no-lookahead via 1-bar signal shift
- Adding a custom provider adapter costs more than the benefit delivers
- Our existing manual translations are already validated (20 tests passing)

---

## What To Do Instead

### For Pine → Python translation (strategy logic only)

Option A (current): Manually translate from Alorse/pinescript-strategies.
Fast, already works, already tested. Continue this.

Option B (future, low priority): Use PyneSys Discord bot to convert
Pine → PyneCore Python, then manually adapt the logic to our
`StrategyFn` contract. Saves reading Pine syntax but adds adapter step.
Only worth it once we have 10+ strategies to translate.

### For live signal execution (future, not current priority)

PyneCore's bar-by-bar import hook model is the right architecture for
LIVE signal generation (not backtesting). If we ever need to run a
strategy on live tick data before routing to a bot, revisit PyneCore
as the execution layer at that time.

---

## Next Priority (formerly P3)

**PBO Score (Probability of Backtest Overfitting)**

Implement via Combinatorially Symmetric Cross-Validation (CSCV).
Reference: arxiv 1905.05023
~50 lines of Python on top of `_completed_trade_returns`.
Adds `pbo_score: float` to `BacktestMetrics`.
Strong signal that complements walk-forward pass rate.
