# Claude Handoff — Pine Strategy Lab Metrics v2 + Scanner v2

Date: 2026-06-28
Tests passing: 20/20

## What Was Built This Session

### 1. BacktestMetrics — 3 new fields (`research/pine_strategy_lab.py`)

```python
sharpe_ratio: float = 0.0        # annualized, daily bars, 252 days/year
win_rate_pct: float = 0.0        # % of closed trades that were winners
calmar_ratio: float = 0.0        # total_return_pct / max_drawdown_pct
```

### 2. Backtester upgrades (`research/pine_strategy_lab_backtest.py`)

**Sharpe ratio helper:**
```python
def _sharpe_ratio(daily_returns: pd.Series) -> float:
    return float((daily_returns.mean() / daily_returns.std()) * (252 ** 0.5))
```

**`_metrics_from_equity` now returns** sharpe_ratio, win_rate_pct, calmar_ratio.

**`BacktestConfig` new field:** `purge_bars: int = 5`

**Walk-forward purge gap (academic standard fix):**
- Was: IS and OOS splits shared boundary bars → information leakage
- Now: `oos_start = is_end + purge_bars` — 5 bars dropped between IS/OOS
- Strategy gets full fold for indicator warmup; signals evaluated on OOS slice only

### 3. Red-flag scanner — 2 new warnings (`research/pine_strategy_lab.py`)

| flag_id | trigger | reason |
|---|---|---|
| `fill_on_price_change` | `fill_orders_on_price_change=true` | Limit orders fill on any intrabar tick, overstating fill rate |
| `pine_v6` | `//@version=6` at line start | v6 changed order execution model; requires re-validation |

Both are warnings (score -0.4 each), not critical (no auto-reject).

### 4. Confidence scoring update

```python
# Sharpe bonus: up to +0.6 for Sharpe >= 3.0 (only when explicitly computed)
if metrics.sharpe_ratio > 0:
    score += min(metrics.sharpe_ratio / 3.0, 1.0) * 0.6
```

### 5. Report table — 2 new columns

`| ... | Sharpe | WR% | Trades | ...`

### 6. Tests — 3 new tests (20 total)

- `test_scan_detects_fill_on_price_change`
- `test_scan_detects_pine_v6`
- `test_scan_v6_is_warning_not_critical`
- Extended `test_backtest_metrics_use_completed_trade_pnl_not_bar_returns` with win_rate_pct, sharpe_ratio > 0, calmar_ratio > 0 assertions

---

## Research Findings (from last30days web search this session)

### PyneCore / PyneSys — EVALUATE NOW

- **Website:** pynesys.io | **GitHub:** github.com/PyneSys/pynecore
- PyneSys compiles Pine Script → Python via deterministic lexical parser/AST (no LLM)
- PyneCore runs the output with "highly compatible" TradingView results
- Supports Pine Script v6 scripts up to 25KB
- Free: up to 3 conversions via their Discord bot (`/pyne-help`)
- This is P2 from the prior handoff — test it NOW on `vwap_pullback_python.py`

### PineTS (JavaScript — monitor, don't integrate yet)

- GitHub: github.com/LuxAlgo/PineTS
- LuxAlgo's 1:1 Pine Script transpiler/runtime for Node.js
- Useful reference for repaint-safe execution semantics; not Python

### Strategy Translation Queue

- **github.com/Alorse/pinescript-strategies** — 48 strategies (10 trend, 14 momentum, 8 mean reversion), MPL/MIT licensed, updated Feb 2026
- **github.com/pAulseperformance/awesome-pinescript** — ecosystem index

These are the input queues for the sweep runner.

### Academic Backtesting Standards

- **AlgoXpert Alpha Research Framework (arxiv 2603.09219):** IS → WFA (purge gaps) → OOS — NOW IMPLEMENTED
- **PBO (Probability of Backtest Overfitting)** via CSCV (arxiv 1905.05023) — next major upgrade
- **Pine v6 backtest behavior changes** documented at blog.traderspost.io/article/pine-script-v6-strategy-changes

---

## What Codex Should Build Next

### P1 — Strategy Sweep Runner (`scripts/strategy_sweep_runner.py`)

Sweep VWAP, EMA, ORB, RSI strategies across:
- Symbols: SPY, QQQ, IWM
- Date ranges: 2020-2024, 2022-2024
- Parameter grids (short/mid/long window sizes)

Output: symbol × period × params → BacktestMetrics table. Flag param combos that only pass IS.

Source strategies to sweep first:
1. `research/pine_strategy_lab/examples/vwap_pullback_python.py` (exists)
2. `ema_crossover_python.py` (translate from Alorse/pinescript-strategies)
3. `orb_breakout_python.py` (translate from same)
4. `rsi_mean_reversion_python.py` (translate from same)

### P2 — PyneCore Integration Test

1. Use PyneSys Discord bot to convert `vwap_pullback_python.py` equivalent Pine back to Python
2. Run both versions on same OHLCV data (SPY 2022-2024)
3. Compare: trade_count, profit_factor, max_drawdown — must match within 2%
4. If it passes: document integration path in `scripts/pine_backtest_runner.py`
5. If it fails: document exact divergence and skip integration

### P3 — PBO Score (Probability of Backtest Overfitting)

Add to `BacktestMetrics`:
```python
pbo_score: float = 0.0  # 0=likely real edge, 1=likely overfit
```

Implement using Combinatorially Symmetric Cross-Validation on `_completed_trade_returns`.
Reference: arxiv 1905.05023 — ~50 lines of Python on top of existing trade data.

---

## Safety Rules — Do Not Break

```
No Pine-derived strategy → flip_bot.py or shadow_pullback_signal.py directly.

Route must be:
  pine_strategy_lab report (pass all gates)
  → red-flag scanner (zero critical flags)
  → paper/shadow module
  → 30+ forward-test signals
  → confidence ≥ 9/10
  → only then: execution candidate
```

## Running the Lab

```powershell
# All tests
uv run --no-project --with pytest --with pandas python -m pytest test_pine_strategy_lab.py -q

# Scan manifest and generate report
uv run --no-project python scripts\pine_strategy_lab_report.py --manifest research\pine_strategy_lab\example_manifest.json

# Backtest a translated strategy
uv run --no-project --with yfinance python scripts\pine_backtest_runner.py --strategy research\pine_strategy_lab\examples\vwap_pullback_python.py --symbol SPY --start 2022-01-01 --end 2024-12-31
```
