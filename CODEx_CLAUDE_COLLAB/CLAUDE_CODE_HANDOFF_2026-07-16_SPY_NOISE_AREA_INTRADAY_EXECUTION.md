# Claude Code Handoff - SPY Noise Area and Recurring Intraday Execution

Date: 2026-07-16 CT

## Objective completed

Implemented the next SPY mastery build while preserving the cash-live safety
boundary:

1. SPY Noise Area plus VWAP model.
2. One-contract Alpaca paper execution lane for qualified Noise Area signals.
3. Recurring intraday SPY scans so ORB retests that form after 9:35 ET can
   actually reach execution.
4. ATM vs 0.60-delta ITM vs OTM contract-selection telemetry.
5. Midpoint, midpoint-plus-one-tick, and marketable-ask execution challengers.
6. Read-only daily execution-challenger report and scheduled task.

## Critical operational finding

The dedicated `Flip-Bot-Entry` task ran only once at 9:35 ET. The 15-minute
task ran `--monitor` only. A 5-minute ORB retest frequently forms after 9:35,
so the bot could correctly detect the setup in code but never scan for a live
paper entry at the right time.

`scripts/run_flip_bot_monitor.ps1` now:

1. Runs `--monitor` first so open-trade protection keeps priority.
2. Stops if monitoring fails.
3. Runs `--intraday-entry` after successful monitoring.

The recurring intraday lane is hard-blocked when `ALPACA_PAPER=false`.

## Paper execution authority

Intraday candidate order:

1. Existing SPY 5-minute ORB breakout/retest.
2. Noise Area plus VWAP only when ORB has no valid candidate.

Noise Area requirements:

- `ALPACA_PAPER=true`.
- `FLIP_NOISE_AREA_PAPER_ENABLED=true`.
- 14 completed prior sessions.
- Scheduled 30-minute checkpoint from 10:00 through 13:00 ET.
- Price above upper band and VWAP for calls, or below lower band and VWAP for
  puts.
- One contract maximum.
- Existing execution guard, spread cap, daily loss, open-position, same-day
  reentry, kill-switch, and broker-position checks all remain active.

Noise Area exits retain the existing +75%, -30%, ratchet, and time exits. A
paper-only structural exit was added when SPY loses the relevant band/VWAP
stop.

## Files added

- `strategies/spy_noise_area.py`
- `scripts/flip_execution_challenger_report.py`
- `scripts/run_flip_execution_challenger_report.ps1`
- `scripts/register_flip_execution_challenger_report_task.ps1`
- `agent/tests/test_spy_noise_area.py`
- `agent/tests/test_flip_noise_area_paper.py`
- `agent/tests/test_flip_execution_challenger_report.py`

## Files changed

- `strategies/flip_bot.py`
- `scripts/run_flip_bot_entry.ps1`
- `scripts/run_flip_bot_monitor.ps1`
- `agent/tests/test_flip_bot_safety.py`
- `agent/tests/test_flip_equity_curve_report.py`

The equity-curve runtime test no longer freezes the live dataset at exactly 10
trades. The account now has 11 post-hardening trades, so the old assertion was
stale by design.

## Contract and execution challengers

Each future accelerated shadow lifecycle can now record:

- `atm`
- `itm_delta_60` when an Alpaca Greek snapshot between 0.55 and 0.70 absolute
  delta is available
- `otm_1`
- `otm_2`

Each variant records:

- point-in-time bid, ask, midpoint, delta, and quote age
- passive midpoint limit
- midpoint plus one cent
- marketable limit at displayed ask
- future observed-ask fill opportunities
- executable ask-entry / bid-exit return

These challengers cannot submit orders or self-promote.

## Baseline report

Before the new fields begin accumulating, the existing 82 completed shadow
lifecycles show:

- ATM average executable return: -8.77%
- OTM-1 average executable return: -9.63%
- OTM-2 average executable return: -17.64%

This is an aggregate baseline across old shadow lifecycles, not a setup-specific
SPY result. It demonstrates why setup isolation and the ITM lane are necessary.

## Scheduled task

Registered and Ready:

`\VibeTrade\FlipExecutionChallengerReport` at 19:24 local time daily.

## Verification completed

Focused implementation suite:

```powershell
python -m pytest agent/tests/test_spy_noise_area.py agent/tests/test_flip_noise_area_paper.py agent/tests/test_flip_execution_challenger_report.py agent/tests/test_flip_entry_quality.py agent/tests/test_flip_bot_safety.py -q
```

Result: 72 passed before the final paper-boundary test, then 169 Flip/SPY tests
passed in the broader focused run.

```powershell
python -m pytest agent/tests -k 'flip or spy_noise_area' -q
```

Result: 169 passed, 3727 deselected.

```powershell
python scripts/execution_gate_audit.py --print
python scripts/risk_fail_closed_proof.py --print
```

Results:

- Execution gate: passed, 99 signals, 0 issues, 1 known read-only warning.
- Reconciliation proof: 4/4 passed.

Full suite:

- 3,884 passed, 4 skipped, 8 failed.
- One failure was the stale 10-trade runtime assertion and is fixed now.
- Seven Futu/Mootdx failures were order-dependent mock pollution; both files
  pass independently, 50/50.
- Focused Futu/Mootdx/equity rerun after the test repair: 68 passed.

## Tomorrow host checks

Before the open:

```powershell
Select-String -Path agent\.env -Pattern '^ALPACA_PAPER='
Get-ScheduledTask -TaskName 'Flip-Bot-Monitor' | Select-Object TaskName,State
Get-ScheduledTask -TaskPath '\VibeTrade\' -TaskName 'FlipExecutionChallengerReport' | Select-Object TaskName,State
```

Expected: `ALPACA_PAPER=true`, both tasks Ready.

After 10:00 ET:

```powershell
Get-Content $HOME\.vibe-trading\logs\flip-bot.log -Tail 250 | Select-String 'INTRADAY SPY|ORB retest|Noise Area|PAPER RESEARCH|ENTRY'
Get-Content $HOME\.vibe-trading\logs\flip-decisions.jsonl -Tail 100
python scripts\flip_execution_challenger_report.py --print
```

Confirm:

- Intraday scans occur after monitor runs.
- A valid ORB remains first priority.
- Noise Area only appears when ORB has no valid candidate.
- Any Noise Area entry has `execution_lane=paper_research`, `paper_only=true`,
  and `contracts=1` in `flip-trades.json`.
- `itm_delta_60` begins accumulating when Alpaca Greeks are available.

## Do not change

- Do not enable the recurring intraday lane for cash-live trading.
- Do not increase the one-contract Noise Area cap.
- Do not weaken reconciliation, kill switch, daily loss, spread, quote, or
  duplicate-position controls.
- Do not give GEX, social signals, or AI forecasts hard-veto authority.
- Do not promote passive limits from indicative Alpaca observations. Licensed
  OPRA/NBBO data is still required for execution-grade fill proof.

## Next evidence milestone

Report SPY results separately by strategy:

- `0dte` with `orb_entry_pattern=breakout_retest`
- `noise_area_vwap`
- 15-minute ORB shadow
- failed-level sweep shadow

The first useful review is 20 completed forward paths per setup. Promotion or
sizing changes still require the stricter preregistered holdout standards.
