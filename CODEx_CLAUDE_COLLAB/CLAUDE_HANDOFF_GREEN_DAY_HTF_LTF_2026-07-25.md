# Claude Code Handoff: Green-Day Reverse Engineering and HTF/LTF Edge

Repository:

`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Ultimate goal: build three independently validated, self-improving but
fail-closed paper systems (Flip, options premium, and Topstep/MES) that can
eventually produce consistent risk-adjusted returns without manufacturing
confidence through retuning. Current capital reference is $1,000. No live
strategy should be promoted until its own forward gate passes.

## Codex Work Completed

New files:

- `research/GREEN_DAY_HTF_LTF_PREREGISTRATION_2026-07-25.md`
- `research/green_day_htf_ltf_lab.py`
- `research/GREEN_DAY_HTF_LTF_RESULTS_2026-07-25.md`
- `agent/tests/test_green_day_htf_ltf_lab.py`
- `data/green_day_htf_ltf_results.json`
- `data/higher_timeframe_volume_screen_lab_rerun_2026-07-25.json`

Commands:

```powershell
uv run --no-project --with pandas --with numpy --with pyarrow --with pytest `
  pytest -q agent/tests/test_green_day_htf_ltf_lab.py `
  agent/tests/test_higher_timeframe_volume_screen_lab.py `
  agent/tests/test_flip_shadow_pnl_evaluator.py `
  agent/tests/test_accelerated_bot_learning_report.py `
  agent/tests/test_lifecycle_normalizer.py

uv run --no-project --with pandas --with numpy --with pyarrow `
  python research/green_day_htf_ltf_lab.py
```

Verification: 35 relevant tests pass.

## Hard Results

### Actual Flip

- Current-cap cohort: 12 trades, 8 wins, 4 losses, +$2,332.
- Excluded pre-hardening 69-contract loss: -$11,557.50.
- Winners clustered June 29-July 6 at 10:30 ET.
- Later July 7/16/17 entries lost.
- Weekly-aligned actual subset: 5 wins / 2 losses.
- Daily-aligned actual subset: 0 wins / 1 loss.
- Three large July 2 PUT wins were counter to bullish weekly/monthly trend.

### Historical SPY, strict IEX coverage

- 467/1,137 sessions complete through 13:45.
- Frozen 10:30 LTF-only 60-minute expectancy:
  - 2022-23: +1.90 bps, n=51, PF 1.14
  - 2024: -5.52 bps, n=8, PF 0.27
  - 2025+: -0.87 bps, n=61, PF 0.93
- HTF alignment does not rescue 10:30.
- Best lead is 12:00 daily-aligned:
  - +2.54 / +10.29 / +5.64 bps across dev/selection/2025+
  - but n=3 selection, negative CI lower bounds, negative after top-1% removal
    in 2025+, and negative fixed-bracket expectancy.

### Shadow Episodes

- 456 completed lifecycle outcomes.
- Only daily+weekly alignment is positive episode-level:
  +0.54% over 54 episodes, but just six date clusters.
- CI crosses zero and top-1%-removed expectancy is -1.70%.

### Higher Timeframes

Rerun on 29 current liquid symbols:

- Monthly price-trend baseline: dev +225.1 bps, selection +263.3 bps,
  final +297.7 bps, final PF 3.51, +277.7 bps at triple costs.
- Weekly RVOL+dual trend: final +58.9 bps, PF 1.67, but bootstrap lower
  bound is slightly negative.
- Monthly RVOL filter harms the baseline. Do not add volume merely for
  confluence.

## Claude's Required Stance

Attack the result. Do not make it prettier.

1. Audit `green_day_htf_ltf_lab.py` for look-ahead, timezone, bar-label,
   resampling, stale-cache, duplicate-trade, and same-bar stop/target errors.
2. Independently reproduce the key tables from raw files rather than trusting
   the JSON report.
3. Verify that HTF labels use only completed periods. Friday's unfinished week
   and the current month must never influence an intraday entry.
4. Quantify selection bias from requiring complete IEX sessions. Do not
   forward-fill missing bars. If a fuller zero-cost source exists, create a
   new preregistered replication.
5. Do not retune checkpoints, MA lengths, targets, stops, or feature weights
   against the consumed data.

## Recommended Improvements

### P0: Evidence Integrity

- Add source timestamp, schema version, daily/weekly/monthly states, and cache
  provenance directly to every future Flip and options shadow entry.
- Implement fill-derived options lifecycle P&L. Twelve of thirteen legacy
  options records previously lacked reliable realized P&L; outcome-text labels
  cannot train a profitability loop.
- Register this experiment in the immutable trial registry before any follow-up
  variant is run.

### P1: Forward-Only Challenger

Create one new shadow-only lane:

- SPY only
- 12:00 ET
- existing 9/9 VWAP/EMA recipe
- prior completed daily state aligned
- 60-minute observation horizon
- no order placement
- frozen before first signal
- minimum 30 resolved independent dates, not 30 correlated symbols

Record both underlying and actual point-in-time option NBBO. Do not use the
historical result to choose a new stop.

### P1: Monthly Rotation Replication

- Rebuild the monthly trend test with survivorship-aware historical membership,
  delisted securities where possible, benchmark-relative return, taxes, and a
  realistic $1,000 fractional-share implementation.
- Compare against buy-and-hold SPY and the existing 50%-deployed momentum lane.
- Preserve the current final period; use new forward months as the real gate.

### P2: Contract Replay

Use the confirmed free Alpaca historical SPY option minute bars/trades for
expired contracts. Calibrate conservative spread stress from
`point_in_time_quotes.py` until historical NBBO is available. Compare 0DTE,
1DTE, and 3-7DTE without claiming underlying returns are option returns.

### P2: Learning Loop

The loop may:

- log immutable evidence;
- diagnose feature/regime clusters;
- nominate one preregistered challenger;
- resolve outcomes; and
- retire failed challengers.

The loop may not:

- mutate live thresholds;
- mix Flip, credit-spread, and MES P&L semantics;
- count correlated same-day symbols as independent evidence;
- relearn from closing-reason regex estimates; or
- promote on backtest results alone.

## Safety Boundaries

- Do not enable live order placement.
- Do not change Flip/options risk, sizing, stops, or targets.
- Keep the MES/Topstep scheduled task disabled.
- Do not spend money or activate Databento billing.
- Work with the dirty tree; never revert unrelated user/generated files.
- Stop after the adversarial audit and proposed patch set for review.
