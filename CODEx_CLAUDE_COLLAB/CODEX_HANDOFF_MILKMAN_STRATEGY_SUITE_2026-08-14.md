# Codex Handoff: Milkman Five-Strategy Research Suite

Date: 2026-08-14

## Objective

Implement the five candidates listed on Milkman Trades without granting a
public backtest execution authority or guessing unpublished rules.

## Delivered

### Core implementation

`research/milkman_strategy_suite.py`

The module is standard-library-only and has no broker imports, credentials,
order methods, scheduler registration, or production configuration access.
Every candidate includes:

- `execution_enabled: false`
- `can_submit_orders: false`

Implemented rule engines:

1. `spx_weekly_atr_candidate`
   - Prior completed weekly close minus prior completed Wilder ATR(14).
   - Half-up rounding to five points.
   - 50-point protective wing.
   - Requires point-in-time natural short bid and long ask.
   - Blocks non-positive natural credit.
   - Calculates structural maximum loss.
   - Complements the existing
     `research/spx_weekly_atr_put_spread_lab.py` underlying audit.

2. `first_five_compression_boxes`, `daily_bilbo_entry`, and
   `daily_bilbo_exit`
   - First-five compression box.
   - Order arms only after the locking close.
   - Twenty-session working period.
   - Prior-close EMA21 gate.
   - Conservative cancellation if high and low both trade in one daily bar.
   - Gap-honest initial/EMA50 ratchet stop.
   - Optional scr3 exit.
   - Mandatory pre-earnings flatten interface.
   - Compression state must be externally verified; the module does not guess
     Saty's unpublished compression parameters.

3. `bilbo_option_entry_gate`, `select_bilbo_option`, and
   `bilbo_option_exit`
   - Confirmed hourly close above box.
   - Published 10:00-15:00 ET weekday entry window.
   - Same-clock median-volume gate and prior-daily EMA21 gate.
   - Expiry nearest 28 DTE within 21-37 DTE.
   - Strike nearest spot plus 0.75 daily ATR.
   - Two-sided quote no wider than 5% of midpoint.
   - Entry benchmark halfway from midpoint to ask.
   - Underlying-based box, +1 ATR/giveback, and time exits.
   - Source 4% allocation is recorded but rejected; research cap is 2% until
     a concurrency-aware sizing study is complete.

4. `swing_golden_gate_levels`, `swing_golden_gate_entry`, and
   `swing_golden_gate_exit`
   - Monthly pivot and -0.382/-0.618/-1.0 ATR geometry.
   - Above-EMA21 state captured when the gate opens.
   - Gap-honest short entry.
   - Pivot stop, -1 ATR target, month-end exit.
   - Same-bar stop/target conflicts are stop first.
   - Candidate explicitly requires a correlated cluster risk budget.

5. `zero_dte_pin_convergence_candidate`
   - Always blocked because the source marks this strategy "coming soon" and
     publishes no deterministic rules or validation.
   - Records supplied context fields but cannot infer thresholds, structures,
     or exits.

### Supporting files

- `agent/tests/test_milkman_strategy_suite.py`
- `research/MILKMAN_STRATEGY_SUITE_PREREGISTRATION_2026-08-14.md`
- `scripts/run_milkman_strategy_suite.ps1`

The runner only writes/prints the static research status report. It is not
registered as a task.

## Verification

Commands:

```powershell
python -m py_compile research\milkman_strategy_suite.py
python -m pytest agent\tests\test_milkman_strategy_suite.py agent\tests\test_spx_weekly_atr_put_spread_lab.py agent\tests\test_execution_gate_audit.py agent\tests\test_new_strategy_lifecycle_hardening.py -q
```

Result: `35 passed`.

Full repository run:

```powershell
python -m pytest agent\tests -q
```

Result: `4667 passed, 4 skipped, 1 failed`.

The single failure is unrelated to this change:

```text
agent/tests/test_shadow_volume_coverage.py
KeyError: 'swing_cash_sleeve_shadow.py'
research/shadow_volume_coverage.py:73
```

The existing `research/shadow_volume_coverage.py` has no `LOGS` entry for the
existing `swing_cash_sleeve_shadow.py`. Codex did not alter that concurrent
user/Claude work.

## Source Findings Claude Must Preserve

### SPX weekly ATR spread

- The source reports an average 2.98-point credit against about $4,700 maximum
  loss. A generic 33% credit-to-risk gate does not describe this strategy.
- Do not relax any global gate. Give this candidate a separate strategy-level
  expected-loss model.
- Underlying settlement frequency cannot establish option profitability.
  Historical point-in-time SPXW quotes and official settlements are mandatory.
- Test XSP and SPY separately. SPX evidence does not transfer automatically.

### Daily Bilbo and Bilbo Options v2

- Public pages describe compression as Bollinger Bands inside an ATR/Keltner
  envelope but do not publish enough parameters to reproduce Saty's exact
  compression flag.
- Accept a vendor/exported compression boolean or create a separately named,
  preregistered public squeeze proxy. Never label a proxy an exact replication.
- The Bilbo v2 page says a ten-trading-day cap, but the forward-paper JSON on
  2026-08-14 showed `cap_days: 14`. The implementation freezes the published
  ten-day rule. Resolve this discrepancy with the author/source before comparing
  our outcomes to the paper sleeve.
- The forward options paper sleeve had only 20 closed trades; its two largest
  winners exceeded total net profit. Tail-contribution tests are mandatory.

### Swing Golden Gate

- The source reports a frozen 2025-2026 pass, but also reports that a separate
  broker-bar reconstruction for 2010-2024 was approximately flat.
- Reproduce on a second adjusted data source before forward shadow collection.
- Stock short is the clean source expression. Long puts lose most of the edge
  when crossing the full spread.

### 0DTE Pin Convergence

- Do not build a guessed pin strategy.
- Wait for exact pin definition, gamma source/snapshot timing, entry window,
  structure, thresholds, exits, costs, and a frozen validation sample.

## Claude Next Actions

1. Review the pure rule engines for source fidelity. Do not add broker code.
2. Resolve the unrelated shadow-volume `LOGS` failure separately, preserving
   concurrent work ownership.
3. Add point-in-time data adapters:
   - Official SPXW settlement plus historical 09:58-10:02 ET bid/ask snapshots.
   - Split-adjusted daily equities plus point-in-time earnings dates.
   - Extended-hours hourly bars, RTH signal hours, five-minute exits, and option
     NBBO timestamps for Bilbo v2.
   - A second broker-quality daily source for Swing Golden Gate.
4. Build independent replay reports with:
   - Development, selection, and untouched final windows.
   - Natural and stressed execution.
   - Day-clustered bootstrap and Deflated Sharpe.
   - Leave-one-symbol/year-out tests.
   - Top 1% and top 5% winner removal.
   - Concurrency-aware drawdown, expected shortfall, and cluster exposure.
5. Feed observations into the existing evidence factory only after schema and
   source timestamps are complete.
6. Do not schedule any lane until its data adapter passes point-in-time tests.
7. Do not promote any lane without Kenny's explicit paper approval after the
   preregistered evidence gate passes.

## Operational State

- No production strategy was modified.
- No environment variable was modified.
- No scheduled task was added or changed.
- No broker connection was added.
- No orders were submitted.
