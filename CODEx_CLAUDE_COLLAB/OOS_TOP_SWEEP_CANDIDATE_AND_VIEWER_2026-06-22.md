# OOS Top Sweep Candidate + Shadow Viewer - 2026-06-22

## Claude Sweep Result Reviewed

Claude's train-only sweep selected:

```text
st80 tol8 partial gap
```

Meaning:
- 1h data
- Opening gap bias enabled
- Partial exit model enabled
- 80-tick pullback stop
- 8-tick pullback tolerance
- No key-level filter
- No BOS filter

Codex validated the exact candidate out of sample.

## OOS Command

```powershell
python strategies\topstep_replay_backtester.py --csv examples\nq_1h_730d.csv --symbol MNQ --signal-type pullback --range-minutes 1 --min-breakout-points 20.0 --reward-risk 2.0 --pullback-stop-ticks 80 --pullback-tolerance-ticks 8 --slippage-ticks 1 --commission 4.00 --exit-model partial_1r_be_2r --require-opening-gap-bias --consistency-penalty 25 --train-end 2025-09-05
```

Train:
- P&L: `$473.75`
- WR: `81.8%`
- PF: `3.90`
- Expectancy: `$43.07/trade`
- Max DD: `$105.50`
- Trades: `11`
- Violations: `1`
- Score: `18.07`

Test:
- P&L: `$89.50`
- WR: `75.0%`
- PF: `1.68`
- Expectancy: `$22.38/trade`
- Max DD: `$132.50`
- Trades: `4`
- Violations: `2`
- Score: `-27.62`

## Verdict

This is the best forward-test candidate so far, but not enough for combine/live.

Why it is promising:
- Positive train and test expectancy.
- Test win rate held up.
- Gap bias remains the strongest filter.
- Partial exit improved train quality in the sweep.

Why confidence stays limited:
- Test sample is only 4 trades.
- Test still has 2 consistency violations.
- 1h candles still hide the real 1m/5m execution structure.

Updated confidence:
- Backtester reliability: `9.3/10`
- Top candidate paper confidence: `5.8/10`
- Combine-readiness: `3.0/10`

## Sweep Harness Patch

File:
`scripts/sweep_train.py`

Changed:
- Added `--penalty`
- Default penalty is now `25.0`
- Both 1h and 5m specs use the selected penalty

Verification command:

```powershell
python scripts\sweep_train.py --top 3 --min-trades 5 --workers 2
```

Result:

```text
st80 tol8 part gap      score 18.07
st80 tol16 part gap     score 7.88
st20 tol8 full gap      score -0.36
```

## Shadow Signal Viewer Built

File:
`scripts/view_shadow_signals.py`

Purpose:
- Read-only viewer for `~\.vibe-trading\shadow-ai-signals.jsonl`
- Shows created time, symbol, strategy, side, entry, stop, target, confidence, outcome, and P&L
- Handles missing/empty journal gracefully
- Supports:
  - `--journal`
  - `--strategy`
  - `--limit`
  - `--json`

Current run:

```powershell
python scripts\view_shadow_signals.py
```

Result:

```text
No shadow signals found.
Journal: C:\Users\kenne\.vibe-trading\shadow-ai-signals.jsonl
```

That is expected. The scanner has not logged forward signals yet.

## Next Best Work

1. Update `strategies/shadow_pullback_signal.py` to use the new best candidate:
   - tolerance 8
   - exit model is only for backtest, not signal generation
   - gap bias check needs to be added to scanner before logging
2. Set up Task Scheduler for the scanner.
3. After signals log, run:

```powershell
python scripts\view_shadow_signals.py --strategy first_pullback_1h
```

4. Build an outcome updater later:
   - Fetch subsequent bars
   - Mark target, stop, partial, breakeven, or EOD
   - Write outcome records or a separate reviewed journal

Do not open a Topstep Combine yet. Forward-test first.
