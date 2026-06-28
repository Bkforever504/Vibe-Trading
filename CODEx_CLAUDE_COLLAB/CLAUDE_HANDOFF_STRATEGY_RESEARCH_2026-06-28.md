# CLAUDE HANDOFF — Strategy Research Session 2026-06-28

## What Was Completed This Session

### 1. KAMA Shadow Logger — DONE, running
- File: `scripts/kama_shadow_logger.py`
- Report: `scripts/kama_shadow_report.py`
- Runner: `scripts/run_kama_shadow_logger.ps1`
- Task: `KAMAShadowLogger` — Windows Task Scheduler, weekdays 15:20 CT
- Log: `data/kama_shadow_log.jsonl`
- First signal logged: 2026-06-26, both setups flat (QQQ below KAMA, slope negative)
- Commit: `a3a46cb`

All three shadow loggers now active:
| Logger | Task | Schedule |
|---|---|---|
| Momentum rotation | MomentumShadowLogger | Sat 15:30 CT |
| RSI-2 QQQ | RSI2ShadowLogger | Weekdays 15:20 CT |
| KAMA QQQ | KAMAShadowLogger | Weekdays 15:20 CT |

Forward-test gate: 30 days / 10 entry signals minimum before any execution review.

### 2. The Strat 2-1-2 — REJECTED
- File: `research/pine_strategy_lab/examples/strat_212_python.py`
- Report: `research/pine_strategy_lab/strat_212_sweep_report.md`
- Commit: after KAMA commit

Results: PBO 0.54 (above 0.50 threshold). Rows with ≥30 trades show IS PF 0.92–1.04 (near breakeven). High-PF rows have only 10 trades (1.4/year — not significant). WF capped at 0.60.

Verdict: mechanical daily-bar 2-1-2 has no measurable edge. The Strat is a discretionary multi-TF framework; it doesn't translate to a mechanical daily signal.

### 3. Trustdan Alt45 (Dual-Momentum) — REJECTED
- Backtester: `research/trustdan_alt45_backtest.py`
- Runner: `research/run_alt45_replication.py`
- Report: `research/pine_strategy_lab/trustdan_alt45_replication.md`
- Commit: latest

Results vs Alt10 comparison:
| Window | Alt10 | Alt45 | Trustdan claim |
|---|---|---|---|
| 2015-2024 | 6/13 profitable | 5/13 (38.5%) | 66.67% |
| 2022-2024 | 5/13 profitable | 4/13 (30.8%) | 66.67% |

The RSI dual-momentum gate is neutral-to-slightly-negative vs Alt10. Same 5 profitable symbols in both (SPY, QQQ, MSFT, AMZN, GOOGL). Healthcare/commodities/defensives remain unprofitable on daily yfinance data.

Root cause: same as Alt10 — TradingView bar construction differs from yfinance adjusted daily bars. ATR-based position sizing and pyramiding are highly sensitive to exact bar data.

## Updated Strategy Ranking

1. **Momentum rotation top-2 weekly** — paper candidate, logging live
2. **RSI-2 QQQ mean reversion** — shadow candidate, logging live, conf 9.1
3. **KAMA QQQ trend** — shadow candidate, logging live, conf 9.1 PF 2.53 OOS 3.11
4. Trustdan Alt45 — rejected, data vendor gap
5. Trustdan Alt10 — rejected, data vendor gap
6. Alorse MACD+BB+RSI — rejected, thin sample
7. Alorse RSI+EMA — rejected, drawdown
8. The Strat 2-1-2 — rejected, PBO 0.54

## What Codex Should Evaluate

### Option A: Validate shadow logger data quality
Run `uv run --no-project --with pandas python scripts/rsi2_shadow_report.py` and `kama_shadow_report.py` to verify both loggers are producing clean entries. Check `data/rsi2_shadow_log.jsonl` and `data/kama_shadow_log.jsonl` for any malformed rows.

### Option B: Source trustdan-compatible daily bar data
The core blocker for Alt10/Alt45/Alt46 is that yfinance adjusted daily bars don't match TradingView's bar construction. If Codex can identify and integrate a free daily bar source that matches TradingView (e.g., Polygon.io free tier, Alpha Vantage, or Tiingo), re-run `research/run_alt45_replication.py` on the new data source. Target: reproduce trustdan's 66.67% claim on ≥10/13 symbols.

### Option C: Trustdan Alt46 (Sector-Adaptive)
If Option B not pursued yet, Alt46 is next in the queue (61.90% trustdan claim). It's likely to fail for the same reason as Alt10/Alt45, but it's worth a quick test to confirm the pattern is consistent before closing the trustdan chapter entirely.

Pine file: `research/pine_sources/trustdan-trend-following/pine-scripts/` — search for `alt46`.

### Option D: New Pine source repos
The scanning pipeline found 7 repos so far. There are more on GitHub. Priority: repos with pre-validated backtests and daily-bar strategies (not 2h/intraday).

## Do Not Do

- Do NOT wire any trustdan strategy to any bot until daily bar data issue is resolved.
- Do NOT paper-trade The Strat — discretionary framework, no mechanical edge confirmed.
- Do NOT execute KAMA or RSI-2 — forward-test gate requires 30 days minimum.
- Do NOT test further trustdan alts on yfinance daily bars until data source resolved — the pattern is confirmed, more tests won't change the conclusion.
