---
name: vibe-trading-exit-logic
description: Use when changing Flip Bot profit target, stop loss, ratchet, profit-protect, time exits, partial exits, or capture efficiency.
---

# Vibe-Trading Exit Logic

## Key Constants (`strategies/flip_bot.py`)
| Constant | Value | Purpose |
|---|---|---|
| `PROFIT_MULT` | 1.75 | Primary +75% target multiplier |
| `STOP_MULT` | 0.50 | Hard -50% stop multiplier |
| `PROFIT_PROTECT_ARM_PCT` | 40.0 | Ratchet arms once trade hits +40% |
| `PROFIT_PROTECT_FLOOR_PCT` | 25.0 | Minimum locked profit after ratchet arms |
| `PROFIT_PROTECT_GIVEBACK_PCT` | 15.0 | Close if trade gives back 15pts from peak |

## Ratchet Logic (added 2026-07-06)
Once `best_pnl_pct >= PROFIT_PROTECT_ARM_PCT`:
```python
lock_floor = max(PROFIT_PROTECT_FLOOR_PCT, best_pnl_pct - PROFIT_PROTECT_GIVEBACK_PCT)
# Close if current_pnl_pct < lock_floor
```
**Why**: SPY call peaked +66%, exited at +17% before ratchet. Ratchet now locks ~+51% in that scenario.

## Failure Story: July 6, 2026
- Trade 1: SPY call, peaked +66%, exited ~+17% (+$67.50). Exit failure — ratchet now fixes this.
- Trade 2: SPY call loss (-$242.50). Entry failure (same-day re-entry chase), not exit failure.

## When Changing Exit Logic
1. Update the constant at the top of `flip_bot.py`, not inline.
2. Add/update a test in `agent/tests/test_flip_bot_safety.py`.
3. Check `shadow_pnl_evaluator` reports for simulated ratchet comparison.
4. Run: `python -m pytest agent/tests/test_flip_bot_safety.py -q`

## IWM Options Bot Exits
- Profit target: 50% of credit received.
- Stop: 100% of credit received (max loss = credit × contracts × 100).
- `exit_pending_reason` flag: set when market is closed; retried next session.
- Spread recovery clears `exit_pending_reason` automatically (fixed 2026-07-06).
- Never force-close options when `is_option_market_open()` returns False.

## Red Flags
- Changing `PROFIT_MULT` or `STOP_MULT` without a test update.
- Disabling ratchet without documenting why.
- Any exit path that calls Alpaca when market is closed (causes reject loop).
