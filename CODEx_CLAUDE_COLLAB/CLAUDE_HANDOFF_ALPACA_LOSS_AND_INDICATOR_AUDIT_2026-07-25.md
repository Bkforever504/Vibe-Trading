# Claude Code Handoff: Alpaca Loss Repair And Indicator Audit

Date: 2026-07-25
Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Ultimate Goal

Build durable, evidence-gated paper bots that can eventually earn promotion
without hiding losses, overstating fills, retuning consumed holdouts, or
mistaking expensive indicators for edge. No live capital until independent
forward evidence and execution truth both pass.

## What Codex Found

Flip:

- Four consecutive closed losses after the July 6 profit peak.
- Recent closed P&L: -$591.
- Strict consensus veto would have avoided the two structured recent losses,
  but that counterfactual is small and selection-biased.

Options:

- Alpaca is paper-only.
- Three open groups had optimistic journal credits versus broker fills.
- IWM: $0.62 stored versus $0.40 filled.
- AAPL: $1.04 stored versus $0.86 filled.
- NVDA: $0.57 stored versus $0.49 filled.
- AAPL and NVDA were entered while shared consensus said `stand_aside` with
  seven warnings because the shared gate was advisory at quantity one.

Indicators:

- Earlier lab rejected Killzone, Failed 2, pivots, Heikin-Ashi, VWAP, and HTF
  recipes.
- New preregistered lab independently tested six public paid-suite methodology
  proxies.
- All 12 SPY/MES promotion decisions failed.
- Squeeze release was recently positive but failed 2024, double costs, PF,
  and confidence interval gates.

## Changes To Audit

- `strategies/iwm_options_bot.py`
  - actual broker fill credit is canonical;
  - accepted orders remain pending until a fill;
  - legacy open groups backfill using GET order snapshots;
  - max risk corrects for worse fill;
  - multi-warning `stand_aside` blocks new options entries only.
- `scripts/run_iwm_bot_entry.ps1`
- `scripts/run_iwm_bot_monitor.ps1`
- `agent/tests/test_iwm_options_confidence_gate.py`
- `research/COMMERCIAL_INDICATOR_PROXY_PREREGISTRATION_2026-07-25.md`
- `research/commercial_indicator_proxy_lab.py`
- `agent/tests/test_commercial_indicator_proxy_lab.py`
- `data/commercial_indicator_proxy_results.json`
- `research/COMMERCIAL_INDICATOR_PROXY_RESULTS_2026-07-25.md`

Current state backup:

`C:\Users\kenne\.vibe-trading\backups\options-trades-pre-fill-truth-20260725-211609.json`

## Required Adversarial Review

1. Attack `_apply_entry_fill()` and `_refresh_entry_order_fills()` for Alpaca
   sign convention mistakes, partial-fill races, leg mismatch, duplicate risk
   adjustment, canceled orders, and pending exposure gaps.
2. Verify no option exit or live-execution path was loosened.
3. Attack the commercial proxy lab for look-ahead, resample timestamp errors,
   next-bar execution errors, cost understatement, session leakage, and
   accidental post-result tuning.
4. Recompute results from the frozen preregistration. Do not tune a failed
   family against 2025+.
5. Add a point-in-time blocked-versus-taken outcome logger for the options
   caution gate. Promotion review requires at least 30 independent candidates.
6. Design the next options replay around actual expired-contract one-minute
   Alpaca bars/trades, with conservative spread stress calibrated from forward
   NBBO capture. Do not claim true option profitability from underlying-only
   tests.

## Hard Boundaries

- No live trading.
- No paid data or indicator purchase.
- Do not close or alter current paper positions during review.
- Do not enable MES/Topstep execution.
- Do not promote any commercial indicator family.
- Do not rewrite the frozen preregistration after seeing results.
- Preserve unrelated dirty worktree changes.

## Verification Commands

```powershell
python -m pytest agent/tests/test_iwm_options_confidence_gate.py -q

uv run --no-project --with pandas --with numpy --with pyarrow --with pytest `
  --with yfinance --with alpaca-py --with python-dotenv `
  python -m pytest `
  agent/tests/test_commercial_indicator_proxy_lab.py `
  agent/tests/test_indicator_recipe_lab.py `
  agent/tests/test_failed2_source_matched_lab.py `
  agent/tests/test_iwm_options_confidence_gate.py -q
```

Expected focused result: 42 passed. Downstream options integration result:
68 passed.

## Decision Standard

The goal is not a 10/10-looking backtest. It is a 9/10 or better confidence
process that refuses promotion when the evidence is weak. The current
indicator verdict is reject. The current options changes are paper-risk and
accounting repairs, not proof of profitability.
