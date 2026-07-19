# Claude Code Handoff - Flip Paper-Challenger Promotion

Date: 2026-07-16 CT
Author: Codex
Repo: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

## User Intent

Kenny asked: "Let's promote then handoff to Claude code."

Important interpretation: this is a controlled promotion, not an unrestricted live promotion. The current evidence does not justify bypassing live readiness, kill switches, reconciliation, liquidity, consensus, spread, daily-loss, or same-day-reentry guards.

## What Was Promoted

Promoted the strongest current index challengers into the Flip bot paper-challenger lane:

- QQQ
- IWM
- AAPL
- NVDA

Runner priority is now:

```powershell
$env:FLIP_PAPER_CHALLENGER_SYMBOLS = "QQQ,IWM,AAPL,NVDA"
```

QQQ/IWM are first because today's shadow results showed the strongest index opportunities:

- QQQ PUT shadow: +88.92%, target_75_hit=true
- IWM CALL shadow: +82.80%, target_75_hit=true
- QQQ PUT shadow: +69.65%, target_75_hit=true
- SPY PUT shadow: +53.22%
- AAPL CALL shadow: +43.80%

## Files Changed

### strategies/flip_bot.py

Added `PAPER_CHALLENGER_SYMBOL_ORDER` so the environment order is preserved instead of losing priority through a set.

Added `find_paper_challenger_0dte(account)`:

- Paper mode only.
- Scans promoted symbols through the existing `_find_0dte_for_symbol()` setup builder.
- Uses `allow_calendar_catalyst=False` for challengers.
- Filters to `SHADOW_LIQUIDITY_ALLOWLIST`.
- Excludes primary execution symbols such as SPY.
- Stamps:
  - `execution_lane = "paper_challenger"`
  - `promotion_source = "paper_challenger_0dte"`

Wired it into `run_entry()` after primary SPY 0DTE and before earnings/breakout candidates.

The existing controls still apply after a setup is generated:

- `_execution_authorization()`
- one-contract cap for paper challengers
- same-day reentry blocker
- shadow consensus gate/advice
- execution guard
- max open positions
- daily loss guard
- spread cap

### scripts/run_flip_bot_entry.ps1

Updated promoted paper challengers:

```powershell
$env:FLIP_PAPER_CHALLENGER_SYMBOLS = "QQQ,IWM,AAPL,NVDA"
```

### scripts/run_flip_bot_monitor.ps1

Kept monitor environment aligned with entry:

```powershell
$env:FLIP_PAPER_CHALLENGER_SYMBOLS = "QQQ,IWM,AAPL,NVDA"
```

### agent/tests/test_flip_bot_safety.py

Added tests proving:

- Scheduled runner contains the promoted challenger order.
- Paper challenger 0DTE scanner preserves priority order.
- Only allowlisted promoted symbols are scanned.
- Live mode fails closed and does not scan challengers.

## Verification

Ran:

```powershell
python -m pytest agent\tests\test_flip_bot_safety.py -q
python -m py_compile strategies\flip_bot.py
```

Results:

- 37 passed
- compile clean

## Current Safety State

This did not enable unrestricted live execution.

SPY remains the only default primary execution symbol unless `FLIP_EXECUTION_SYMBOLS` is changed externally.

QQQ/IWM/AAPL/NVDA can now reach the existing paper-challenger execution path with a one-contract cap when the same 0DTE setup builder finds an ORB/gap/catalyst-style opportunity.

If `ALPACA_PAPER=false`, `find_paper_challenger_0dte()` returns `[]` and `_execution_authorization()` blocks challenger symbols unless explicitly promoted into `FLIP_EXECUTION_SYMBOLS`.

## Known Caveats / Next Work

1. This is a paper-challenger promotion, not a live promotion.

2. The watchdog still shows `status=alert` from gate dominance/setup mismatch history:

- `consensus_gate_dominates_qualified_path`
- `setup_agnostic_gate_mismatch`
- positive shadow symbols still stand aside: AAPL, QQQ, SPY

Do not ignore this. The next work is to ensure advisory modules cannot veto setup types they do not understand.

3. The challenger bridge now scans promoted symbols through `_find_0dte_for_symbol()`, but it does not yet select directly from completed shadow lifecycles by score. That is the next competitive jump:

Build a read-only-to-paper bridge that ranks today's active shadow entries by:

- executable return path quality
- target_75 hit rate
- spread at signal
- quote age
- expected-move bucket
- ORB direction
- symbol liquidity
- same-day loss/reentry state

Then allow only the top ranked promoted challenger to become a paper-challenger setup when all hard safety gates pass.

4. Keep `MAX_OPEN_FLIPS=2` unless there is separate evidence and explicit approval. Because only two slots exist, priority order matters.

5. Do not promote COIN/RIVN/NFLX to paper-challenger execution yet from this change. They remain useful shadow/research names, but today's user request was to promote the obvious high-quality index challengers first.

## Claude Code Suggested Next Steps

1. Run:

```powershell
python scripts\elite_bot_readiness_scorecard.py --print
python scripts\bot_behavior_regression_watchdog.py
python scripts\flip_exit_quality_report.py
python scripts\flip_path_telemetry_completeness.py
```

2. Review tomorrow morning's `flip-decisions.jsonl` and `flip_shadow_candidates_log.jsonl` for:

- `promotion_source=paper_challenger_0dte`
- `execution_lane=paper_challenger`
- one-contract capped QQQ/IWM/AAPL/NVDA setups
- whether shadow consensus blocks are still logically mismatched to the setup direction

3. If QQQ/IWM paper-challenger setups are still not firing despite valid shadow winners, build the ranked shadow-to-paper setup selector described above.

4. Do not loosen live execution. Evidence first, then human approval.
