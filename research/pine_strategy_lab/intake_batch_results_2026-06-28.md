# Strategy Intake Batch Results - 2026-06-28

Goal: process every remaining Strategy Intake Factory target back to back, promote only candidates that survive the same evidence gates used by the Pine Strategy Lab, and hand the results to Claude Code.

## Executive Result

| Intake | Strategy | Result | Key Evidence | Next Action |
|---|---|---|---|---|
| intake-002 | Seasonal Best-6-Months MACD | Rejected | Best row had only 20 trades and 32.4% DD | Park |
| intake-003 | Pinbar Reversal Daily | Pending/manual review | No critical repaint flags, but no commission/slippage and unknown license | Low-priority manual port only if license clears |
| intake-004 | ArunKBhaskar Pine collection | Scan-only | 26 indicators, 0 strategies, 2 critical lookahead files | Use as idea library only |
| intake-005 | Weighted Multi-Indicator Confluence | Pending/manual review | One clean Pine strategy, no scanner warnings, unknown license/high PBO risk | Manual review after higher-confidence loggers |
| intake-006 | Month-End Seasonal Momentum | Rejected | Good PF/DD, but PBO 0.83 rejected the family | Park |
| intake-007 | TQQQ/GLD 2-Month Rotation | Paper candidate, modified | TQQQ failed DD; QQQ/GLD passed with conf 9.0 | Build QQQ/GLD shadow logger |
| intake-008 | Williams %R Oversold Bounce | Paper candidate | Multiple SPY/QQQ rows passed, top QQQ conf 10.0 | Build Williams %R shadow logger |

## Backtest Results

### intake-002 - Seasonal Best-6-Months MACD

Python port: `research/pine_strategy_lab/examples/seasonal_macd_best_months_python.py`

Report: `research/pine_strategy_lab/seasonal_macd_best_months_sweep_report.md`

Verdict: rejected.

Best row:

| Symbol | Range | Params | PF | OOS PF | WF | Sharpe | WR | Trades | DD |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| SPY | 2000-2024 | entry_month=10, exit_month=5 | 7.82 | 9.93 | 1.00 | 0.56 | 80.0% | 20 | 32.4% |

Why it failed: the strategy is too sparse for our evidence standard and drawdown exceeded the 25% gate. The headline PF is not enough when it comes from only 20 completed trades.

### intake-006 - Month-End Seasonal Momentum

Python port: `research/pine_strategy_lab/examples/month_end_seasonal_python.py`

Report: `research/pine_strategy_lab/month_end_seasonal_sweep_report.md`

Verdict: rejected.

Best row:

| Symbol | Range | Params | PF | OOS PF | WF | Sharpe | WR | Trades | DD | PBO |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | 2010-2024 | first_days=3, last_days=4 | 1.80 | 1.62 | 1.00 | 1.13 | 75.8% | 186 | 5.7% | 0.83 |

Why it failed: attractive traditional stats, but the family-level PBO score was 0.83, above the 0.60 rejection gate. This is exactly the kind of seasonal parameter mining the lab is meant to catch.

### intake-007 - TQQQ/GLD 2-Month Rotation

Python port: `research/pine_strategy_lab/examples/tqqq_gld_rotation_python.py`

Report: `research/pine_strategy_lab/tqqq_gld_rotation_sweep_report.md`

Verdict: paper candidate only for the nonleveraged QQQ/GLD variant.

Passing rows:

| Symbol | Range | Lookback | PF | OOS PF | WF | Sharpe | WR | Trades | DD | Confidence |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| QQQ | 2018-2024 | 40 | 4.24 | 5.64 | 0.80 | 1.02 | 51.4% | 35 | 24.3% | 9.0 |
| QQQ | 2011-2024 | 42 | 2.28 | 4.61 | 0.60 | 0.74 | 47.2% | 72 | 18.1% | 9.0 |

Important constraint: TQQQ rows failed on drawdown. Do not use TQQQ for the bot. The usable candidate is QQQ vs GLD rotation, then only after forward logging and overlap analysis against the existing momentum rotation bot.

### intake-008 - Williams %R Oversold Bounce

Python port: `research/pine_strategy_lab/examples/williams_r_oversold_python.py`

Report: `research/pine_strategy_lab/williams_r_oversold_sweep_report.md`

Verdict: paper candidate.

Top passing rows:

| Symbol | Range | Params | PF | OOS PF | WF | Sharpe | WR | Trades | DD | Confidence |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| QQQ | 2018-2024 | WR(2), entry=-90, exit=-50, max_hold=5, no trend filter | 2.19 | 2.52 | 1.00 | 1.09 | 67.5% | 114 | 12.7% | 10.0 |
| SPY | 2010-2024 | WR(3), entry=-90, exit=-50, max_hold=5, SMA200 filter | 1.91 | 2.04 | 1.00 | 0.74 | 73.0% | 126 | 11.4% | 10.0 |

Next action: build a Williams %R shadow logger and include an overlap report against RSI-2, because both are oversold mean-reversion families.

## Pine Source Scans

### intake-003 - samgozman Pinbar

Report: `research/pine_sources/samgozman_pinbar_scan_report.md`

Scan result: 1 Pine strategy, 0 critical repaint files, 1 warning file.

Warnings: `no_commission`, `no_slippage`; license unknown.

Decision: keep as manual-review pending. It is clean enough not to reject immediately, but it is lower priority than the validated Williams %R and QQQ/GLD candidates.

### intake-004 - ArunKBhaskar PineScript

Reports:

- `research/pine_sources/arunkbhaskar_scan_report.md`
- `research/pine_sources/arunkbhaskar_normalized_scan_report.md`

Scan result after normalizing `.txt` Pine scripts: 26 indicators, 0 strategies, 4 clean files, 22 warning files, 2 critical repaint files.

Clean idea candidates:

- ICT Market Structure Shift
- Ankush Bajaj Momentum Investing Setup
- Vijay Thakare Option Buying Scalping Setup
- Trend Following Setup - Sideways Market Skipper

Decision: scan-only. This repo can inspire indicator research, but it is not a ready strategy source.

### intake-005 - AlbertoCuadra Weighted Strategy

Report: `research/pine_sources/albertocuadra_weighted_scan_report.md`

Scan result: 1 Pine strategy, 1 clean file, 0 critical repaint files, 0 warnings.

Candidate: `weighted_strategy.pine` / Acrypto Weighted Strategy v1.4.9.

Decision: pending/manual review. It is scanner-clean, but the unknown license and multi-indicator parameter count make PBO risk high. Port narrowly if we work on it later.

## Priority Queue For Claude/Codex

1. Build Williams %R shadow logger for QQQ and SPY.
2. Build QQQ/GLD rotation shadow logger, explicitly excluding TQQQ.
3. Add overlap analysis: Williams %R vs RSI-2, QQQ/GLD vs existing momentum rotation.
4. Defer pinbar and weighted confluence until the two stronger candidates are logging.
5. Treat ArunKBhaskar as an indicator idea library only, never as a copy/paste strategy source.

## Files Created

- `research/pine_strategy_lab/examples/month_end_seasonal_python.py`
- `research/pine_strategy_lab/examples/seasonal_macd_best_months_python.py`
- `research/pine_strategy_lab/examples/tqqq_gld_rotation_python.py`
- `research/pine_strategy_lab/examples/williams_r_oversold_python.py`
- `research/pine_strategy_lab/month_end_seasonal_sweep_report.md`
- `research/pine_strategy_lab/seasonal_macd_best_months_sweep_report.md`
- `research/pine_strategy_lab/tqqq_gld_rotation_sweep_report.md`
- `research/pine_strategy_lab/williams_r_oversold_sweep_report.md`
- `research/pine_sources/samgozman_pinbar_scan_report.md`
- `research/pine_sources/arunkbhaskar_scan_report.md`
- `research/pine_sources/arunkbhaskar_normalized_scan_report.md`
- `research/pine_sources/albertocuadra_weighted_scan_report.md`
- `agent/tests/test_strategy_intake_candidates.py`
