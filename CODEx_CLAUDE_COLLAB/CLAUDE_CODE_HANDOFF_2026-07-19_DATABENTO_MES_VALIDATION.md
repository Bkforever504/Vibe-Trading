# Claude Code Handoff: Databento MES Validation and Trading-System Goal

Date: 2026-07-19
Owner: Kenny
Previous agent: Codex
Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Read This First

Continue from the current repository. Do not rebuild the project, delete dirty
worktree changes, reset Git, enable live trading, or silently loosen any risk or
promotion gate.

The worktree contains many user/agent changes and untracked research artifacts.
Assume all unrelated changes belong to Kenny or another agent. Work only with
the files named in this handoff unless a dependency requires otherwise.

The Databento API key is already stored in `agent/.env` as
`DATABENTO_API_KEY`. Never print, commit, echo, or include it in reports.

## Ultimate Goal

Build a reproducible, automated trading system that can eventually produce
consistent risk-adjusted income while protecting a small account, initially
modeled at $1,000, and potentially qualify for prop-firm simulation.

The user's aspirational target is $100-$200 per trading day. Historical testing
does not support that target from a $1,000 account with low drawdown. Do not
promise or optimize toward a daily dollar quota. The engineering target is:

1. Positive expectancy after realistic and doubled costs.
2. Stable performance across regimes and chronological out-of-sample periods.
3. Drawdown compatible with account survival.
4. Reproducible execution with no rule violations.
5. At least 30 independent forward-simulation trades before any funding review.
6. Explicit user approval before any live or prop-firm execution.

Profitability is probabilistic. A 10/10 profitability-confidence claim is not
valid. Aim for 9/10 confidence in data integrity, test design, execution safety,
and reproducibility.

## Safety State: Do Not Change

- Scheduled task `VibeTradingNinjaTraderMESSim` is `Disabled`.
- The NinjaTrader strategy is research/Strategy-Analyzer only.
- The stale MES Python executor is hard-blocked in
  `strategies/mes_sim_candidate.py`.
- Do not open or pay for a Topstep Combine.
- Do not route futures orders.
- Do not enable live Alpaca/options execution as part of this task.
- The separate `MicroMomentumPaper` lane exists and should remain separate.
- `STATUS.md` reports an unrelated options-state reconciliation issue. Do not
  auto-close positions or rewrite broker state while doing MES research.

## What Codex Built

### Native NinjaTrader strategy

Repository source:
`ninjatrader/VibeMesOrbPullbackResearch.cs`

Installed source:
`C:\Users\kenne\OneDrive\Documents\NinjaTrader 8\bin\Custom\Strategies\VibeMesOrbPullbackResearch.cs`

Compile include added to:
`C:\Users\kenne\OneDrive\Documents\NinjaTrader 8\bin\Custom\NinjaTrader.Custom.csproj`

Properties:

- Strategy Analyzer guard using `IsInStrategyAnalyzer`.
- One-minute primary bars and daily trend series.
- Parameterized opening range, breakout window, breakout size, pullback
  tolerance, fixed stop, and reward/risk.
- VWAP and daily-trend filters.
- One contract and one trade per day.
- Fixed stop/target, slippage, entry cutoff, and end-of-day flatten.
- Defaults use Central time: 08:30 open, 12:00 entry cutoff, 14:55 flatten.

The NinjaScript compiled successfully. Do not enable it on an account.

### Databento importer

Files:

- `scripts/fetch_databento_futures.py`
- `agent/tests/test_fetch_databento_futures.py`
- `data/databento_futures_manifest.json`

Behavior:

- Dataset `GLBX.MDP3`, schema `ohlcv-1m`.
- Continuous volume-front symbol `MES.v.0`.
- Estimate-only by default.
- Requires `--download` and refuses estimates above `--max-cost`.
- Reuses the local `.dbn.zst` cache instead of redownloading.
- Converts timestamps to Eastern time and emits 09:30-16:00 RTH bars.
- Validates OHLC relationships.
- Uses Databento `metadata.get_dataset_condition` and excludes all dates not
  marked `available`.
- Detects continuous-contract instrument changes and excludes recorded roll
  dates, subject to the P0 caveat below.

### Validation search

Files:

- `research/mes_futures_strategy_search.py`
- `agent/tests/test_mes_futures_strategy_search.py`
- `data/mes_databento_validation.json`

The old 80/20 search ranked candidates using its own holdout. Codex corrected
this contamination. Current design:

- First 70%: development search across three internal chronological regimes.
- Next 15%: selection and doubled-cost stress.
- Final 15%: untouched confirmation test.
- Candidate order is frozen before the final test. Do not filter or reorder
  candidates using final-test results.

The executable grid covers:

- ORB and first-pullback signals.
- Opening ranges of 5, 15, and 30 minutes.
- Breakouts of 1, 3, 5, 8, and 12 points.
- Reward/risk values 1.0, 1.5, 2.0, and 2.5.
- Stops of 20 and 40 ticks for the current micro-account cap.
- Pullback tolerances of 4, 8, and 16 ticks.
- Full target/stop exits only in executable mode.
- Existing gap, VIX, trend, EMA, VWAP, and volume filter families.
- One MES contract, maximum one trade per day.

## Data Purchased and Cached

Account billing after download:

- Current balance: $0.00.
- Signup credits before download: $125.00.
- Remaining credits after download: $119.14.
- Actual credit consumed: approximately $5.86.
- No card charge occurred.

Do not redownload this query. Reprocess the cache locally.

DBN cache:
`data/databento/mes_v0_1m_2022-01-01_2026-07-19.dbn.zst`

- Bytes: 25,789,141
- SHA256: `4FB24ACCB849C95050E001A68327A4349E84481E85D6E51602669BE19D0F0EF0`

Normalized CSV:
`examples/mes_v0_1m_2022-01-01_2026-07-19_rth.csv`

- Bytes: 31,154,544
- SHA256 before the P0 roll fix:
  `CA96898AF6672FFE9A84E80D1AD86D5F448AFACDEC7BCCBB38E4946A25B07E45`
- 441,238 one-minute RTH bars.
- 1,150 sessions.
- First bar: 2022-01-03 09:30 ET.
- Last bar: 2026-07-17 15:59 ET.

Validation JSON:
`data/mes_databento_validation.json`

- Bytes: 11,049
- SHA256 before the P0 rerun:
  `23B3F5337BC5719BE7CBB7CA41BFC5A49DBC34ED0633E8EE7F3C872E661CC662`

## Results So Far

### NinjaTrader local-history default

Requested range: 2024-01-01 through 2026-07-18.

Actual local minute data contained only about 32 MES sessions beginning
2026-06-11. NinjaTrader displayed the requested dates, but did not have the full
history. Default 40-tick stop and 2R result:

- Net P&L: -$265.
- Profit factor: 0.60.
- Max drawdown: -$265.
- Sharpe: -0.17.
- Trades: 17.
- Win rate: 23.53%.
- Commission shown as $0, so this was optimistic.

NinjaTrader walk-forward returned zero results because the account was not
subscribed to enough historical contract data. This is why Databento was added.

### First Databento search: one-minute opening range only

- Grid: 1,600 executable configurations.
- Development survivors: 2.
- Selection survivors: 0.

Development survivors failed selection:

1. Pullback, 3-point breakout, 2.5R, 40-tick stop, tolerance 16, live VWAP.
   - Development: 67 trades, $407, PF 1.17, max DD $419.
   - Selection: 21 trades, -$84, PF 0.90, max DD $432.
   - Selection at doubled costs: -$168, PF 0.81.
2. Same geometry with EMA20 filter.
   - Development: 69 trades, $299, PF 1.12, max DD $462.
   - Selection: 24 trades, -$246, PF 0.75, max DD $486.
   - Selection at doubled costs: -$342, PF 0.67.

### Expanded Databento search: 5/15/30-minute opening ranges

- Grid: 4,800 executable configurations.
- Development sessions: 805.
- Selection sessions: 172.
- Untouched final sessions: 173.
- Development survivors: 4.
- Selection survivors: 1.

Selected candidate, frozen before final test:

- Signal: ORB.
- Opening range: 5 minutes.
- Minimum breakout: 1 point.
- Stop: 40 ticks / 10 points / $50 before costs.
- Target: 2R.
- Filter: opening-gap directional bias.
- One trade per day.

Results:

| Stage | Trades | P&L | Expectancy | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| Development | 45 | $570 | $12.67 | 1.42 | $240 |
| Selection | 11 | $156 | $14.18 | 1.48 | $120 |
| Selection, 2x costs | 11 | $112 | $10.18 | 1.32 | $140 |
| Final test | 22 | $12 | $0.55 | 1.02 | $336 |
| Final test, 2x costs | 22 | -$76 | -$3.45 | 0.91 | $372 |

Verdict before the roll-date correction: rejected. It failed final trade count,
profit factor, doubled-cost expectancy, and drawdown gates.

Report:
`research/MES_DATABENTO_VALIDATION_RESULTS_2026-07-19.md`

## P0 Data Caveat Claude Must Fix First

Databento continuous contracts can change `instrument_id` outside RTH, often on
Sunday. The current normalizer records the timestamp's calendar date as a roll
date. Excluding Sunday does nothing to RTH data. The following Monday can still
compare the new contract's open with the old contract's Friday close, creating
an artificial opening gap that contaminates `gap` filter tests.

This does not justify deployment; the current candidate already failed. It does
mean the exact search must be rerun after a correct roll-transition exclusion.

Required fix in `scripts/fetch_databento_futures.py`:

1. For every `instrument_id` transition, locate the first subsequent actual RTH
   session represented in the data.
2. Exclude that full RTH session, even when the transition occurred Sunday or
   overnight.
3. Prefer also recording transition timestamp, old/new instrument IDs, and the
   excluded RTH date in the manifest.
4. Add a test where the instrument changes Sunday and Monday RTH is excluded.
5. Re-normalize from the existing DBN cache. Do not download again.
6. Recompute CSV and manifest hashes.
7. Rerun the entire 4,800-config search with identical gates.

Also audit half-days and incomplete sessions using an exchange-calendar-aware
method. Do not assume all RTH sessions contain 390 bars. Report missing-bar
counts and exclude unexplained incomplete sessions before rerunning.

## Exact Verification Commands

Focused tests currently pass: 52 passed.

```powershell
python -m pytest agent\tests\test_fetch_databento_futures.py agent\tests\test_mes_futures_strategy_search.py agent\tests\test_mes_candidate_stress.py agent\tests\test_topstep_replay_backtester.py -q
```

Reprocess the existing cache after fixing roll handling. This command still
prints an estimate, but `cache_reused` must be `true` and no second data download
should occur:

```powershell
uv run --no-project --with databento --with pandas python scripts\fetch_databento_futures.py --products MES --download --max-cost 6.00
```

Rerun the fixed executable search:

```powershell
python research\mes_futures_strategy_search.py --csv examples\mes_v0_1m_2022-01-01_2026-07-19_rth.csv --executable-only --max-stop-ticks 40 --out data\mes_databento_validation.json
```

Verify the disabled task:

```powershell
Get-ScheduledTask -TaskName "VibeTradingNinjaTraderMESSim"
```

## Promotion Gates: Keep These Fixed

A candidate remains research-only unless all conditions hold:

- At least 30 trades in a genuinely untouched final test.
- Positive final-test expectancy.
- Final-test profit factor at least 1.20.
- Positive doubled-cost expectancy.
- Doubled-cost profit factor at least 1.10.
- Historical max drawdown no greater than $200 per MES contract.
- Monte Carlo 95th-percentile drawdown no greater than $300 on the $1,000 model.
- No prop-rule or execution violations.
- At least 30 later forward-simulation trades after historical validation.

Passing historical gates permits NinjaTrader simulation only. It does not
permit a Topstep purchase, prop account, or live order.

## What Claude Should Do After the P0 Rerun

### If no candidate passes

1. Record the ORB family as rejected under the tested specification.
2. Do not tune parameters against the consumed 2022-2026 final period.
3. Build anchored rolling walk-forward diagnostics to identify whether failure
   is regime-specific, without calling that exercise a new untouched test.
4. Pre-register a materially different hypothesis before coding it. The
   hypothesis must define signal, session, risk, costs, filters, and pass/fail
   gates in a dated Markdown file.
5. Use later forward-simulation data as the next genuinely unseen evidence.

Reasonable independent research families include session momentum with a
volatility-normalized stop, VWAP mean reversion on explicitly classified range
days, and higher-timeframe trend continuation. Do not merely add filters to the
failed 5-minute gap ORB until it fits.

### If a candidate passes after the data fix

1. Add dynamic Monte Carlo and block-bootstrap stress using that selected
   candidate, not the stale hard-coded finalists in
   `research/mes_candidate_stress.py`.
2. Test 1x, 2x, and 3x costs and delayed-entry/slippage shocks.
3. Port the exact frozen configuration into
   `ninjatrader/VibeMesOrbPullbackResearch.cs`.
4. Compile and run NinjaTrader Strategy Analyzer only.
5. Compare Python and NinjaTrader trades date-by-date and price-by-price.
6. Fail closed on any mismatch.
7. Start forward simulation only after parity passes.

## Known Stale Documentation

`CODEx_CLAUDE_COLLAB/TASK_QUEUE.md` still describes tiny yfinance samples and
an old `st80 tol8 partial gap VIX 16-24` candidate. That candidate is superseded
by this deep Databento work and is not combine-ready. Update the task queue after
the corrected rerun.

`STATUS.md` is dated 2026-07-18 and covers the broader bot stack. Preserve its
forbidden actions. Do not overwrite unrelated status findings while updating
the MES section.

## Current Confidence Scores

- Key/security handling: 9/10.
- Fail-closed execution controls: 9/10.
- Validation architecture: 9/10.
- Data integrity before roll-session correction: 7/10.
- Evidence that the tested ORB family is profitable: 2/10.
- Confidence that MES execution must remain disabled now: 9/10.
- Confidence that $100-$200/day is supportable from a $1,000 account: 1/10.

## Definition of Done for Claude

Claude is done only when:

1. Roll-transition and session-completeness handling are fixed and tested.
2. Cached data is re-normalized without another paid download.
3. The full fixed search is rerun and documented.
4. Monte Carlo/stress analysis is dynamic for any passing candidate.
5. Python/NinjaTrader parity is verified if and only if a candidate passes.
6. Scheduled execution remains disabled.
7. `TASK_QUEUE.md` and the final research report reflect the corrected truth.
8. All focused tests pass and exact counts are recorded.
9. No claim of guaranteed or daily-consistent profit is made.
10. A concise next-action handoff is left for Codex and Kenny.
