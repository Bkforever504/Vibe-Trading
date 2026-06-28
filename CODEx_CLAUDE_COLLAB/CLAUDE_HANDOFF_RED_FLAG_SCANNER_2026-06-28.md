# Claude Handoff — Pine Strategy Lab Red-Flag Scanner

Date: 2026-06-28
Commit: 273d3f8

## What Was Built

Added a `scan_pine_red_flags(source)` layer to `research/pine_strategy_lab.py`.
It runs on every Pine file before backtest metrics are scored.

### Critical flags (auto-reject, regardless of metrics):

- `barmerge.lookahead_on` — lookahead bias, results impossible to reproduce live

### Warning flags (score penalty: -0.4 pts each, no auto-reject):

- `request.security()` — multi-timeframe data repaints on unconfirmed realtime bar
- Missing `commission_value=` in `strategy()` — backtest overstates returns
- Missing `slippage=` in `strategy()` — fills at exact price not achievable live
- `process_orders_on_close=true` — fills at bar close, not realistic
- `calc_on_every_tick=true` — tick recalculation repaints in realtime
- `ta.pivothigh / ta.pivotlow` — backward-looking, repaints until future bars confirm

### New dataclasses:

```python
RedFlag(severity, flag_id, message)
RedFlagReport(flags)  # .has_critical, .critical_flags, .warning_flags
```

### Integration:

- `evaluate_candidate(idea, metrics, red_flags=report)` — optional third arg
- Critical flags → added to `reject_reasons` with `[repaint]` prefix
- Warning flags → stored in `CandidateEvaluation.red_flag_warnings`
- `load_manifest_evaluations()` now runs scanner on every Pine file automatically
- `write_candidate_report()` now includes "Red Flag Warnings" column

### Test coverage:

16 tests pass. Red-flag tests added to `test_pine_strategy_lab.py`:
- Each flag detected individually
- Critical flag forces rejection even on metrics that would pass
- Warnings lower score but do not reject
- Report includes red flag column
- Manifest loader auto-scans and rejects on critical flag

### New fixtures:

```
research/pine_strategy_lab/examples/repaint_trap.pine     — triggers 4 flags (critical + 3 warnings)
research/pine_strategy_lab/examples/clean_ema_strategy.pine — triggers zero flags
```

## What Codex Should Build Next

### P0 — Trade-level backtest metrics

Current backtester in `research/pine_strategy_lab_backtest.py` uses bar-level
returns for profit factor. This is v1 and acceptable but not 10/10.

Upgrade `_metrics_from_equity` to track individual completed trades:

Required metrics to add to `BacktestMetrics` or a new `TradeMetrics` dataclass:

```python
avg_win_pct: float
avg_loss_pct: float
expectancy: float          # avg_win * win_rate - avg_loss * (1 - win_rate)
max_consecutive_losses: int
time_in_market_pct: float  # % of bars with open position
```

Track trades by detecting when position transitions from 0→1 (entry) and 1→0 (exit).
Compute P&L per closed trade, not per bar.

### P1 — Strategy sweep runner

Build `scripts/strategy_sweep_runner.py`:

- Takes a strategy Python file
- Sweeps across: symbols (SPY, QQQ, IWM), date ranges (2020-2024, 2022-2024), parameter grids
- Uses `run_backtest` from `pine_strategy_lab_backtest.py`
- Outputs a sweep results table: symbol × period × params → BacktestMetrics
- Flags parameter combinations that only work in-sample (overfit signal)

Strategy families to sweep first (in priority order):
1. VWAP reclaim (already translated: `vwap_pullback_python.py`)
2. EMA crossover (add: `ema_crossover_python.py`)
3. ORB breakout (add: `orb_breakout_python.py`)
4. RSI mean reversion (add: `rsi_mean_reversion_python.py`)

### P2 — PyneCore evaluation

Evaluate whether PyneCore (GitHub) allows running Pine-like logic in Python
without manual translation. Test carefully on a known strategy before integrating.

Do not blindly integrate. Requirements before adoption:
- No lookahead in its execution model
- Handles commission/slippage correctly
- Produces reproducible results vs manual Python translation

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
# Scan manifest and generate report
uv run --no-project python scripts\pine_strategy_lab_report.py --manifest research\pine_strategy_lab\example_manifest.json

# Run all tests
uv run --no-project --with pytest python -m pytest test_pine_strategy_lab.py test_pine_strategy_lab_backtest.py -q

# Backtest a translated strategy
uv run --no-project --with yfinance python scripts\pine_backtest_runner.py --strategy research\pine_strategy_lab\examples\vwap_pullback_python.py --symbol SPY --start 2022-01-01 --end 2024-12-31
```
