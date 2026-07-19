---
name: vibe-trading-risk-memory
description: Use when a past failure should become permanent project memory, or when evaluating current risk against historical blowups.
---

# Vibe-Trading Risk Memory

## Failure 1: The 69-Contract Blowup (2026-06-23)
- **What happened**: Flip Bot entered SPY with `max_risk_pct=0.25` (25%) and no contract cap. At ~$90k equity, this sized to 69 contracts.
- **Loss**: ~-$11,557.50 in one trade
- **Root cause**: Risk parameter 25% × equity ÷ option price = uncapped contracts
- **Fix applied 2026-06-26**:
  - `max_risk_pct` → 0.02 (2%)
  - `MAX_CONTRACTS = 5` hard ceiling added
  - `config_change_date: "2026-06-26"` in signal registry
- **Post-fix record**: 7/7 wins, +$2,855 P&L (as of 2026-07-05)
- **Grade note**: Flip Bot all-time grade is F. Post-fix grade is B. Always report both.

## Failure 2: July 6 Profit Giveback (2026-07-06)
- **What happened**: SPY call peaked +66%, bot held waiting for +75% target, exited ~+17.3%
- **Root cause**: No ratchet — bot allowed full giveback after a large runner
- **Fix applied 2026-07-06**:
  - `PROFIT_PROTECT_ARM_PCT = 40` — ratchet arms at +40%
  - `PROFIT_PROTECT_GIVEBACK_PCT = 15` — close if 15pts given back from peak
  - `PROFIT_PROTECT_FLOOR_PCT = 25` — minimum locked profit
- **Ratchet example**: peaks at +66% → locks at max(25%, 66-15) = +51%

## Failure 3: Same-Day Re-Entry Chase (2026-07-06)
- **What happened**: After first SPY call (profitable), bot took a second SPY call same direction. Lost -$242.50.
- **Root cause**: Entry/regime failure — second entry was a chase after the move had already happened
- **Fix applied 2026-07-06**: Same-day same-symbol same-direction re-entry now blocked unless 10/10 confidence + fresh TTM squeeze + ORB confirmation

## Failure 4: AAPL Options Reject Loop (pre 2026-07-06)
- **What happened**: AAPL put spread past stop threshold. Bot repeatedly sent close orders while market was closed → Alpaca rejected all orders.
- **Fix**: `is_option_market_open()` check before submitting. Failed exits set `exit_pending_reason` and retry next session.

## Permanent Rules Derived from Failures
1. `max_risk_pct ≤ 0.02` always
2. `MAX_CONTRACTS = 5` always
3. Never send option close orders when market is closed
4. Ratchet must be armed for any option position exceeding +40%
5. Same-day same-direction re-entry requires materially stronger setup

## Current Risk State (2026-07-06)
- AAPL put spread: `exit_pending` — exits at Monday open
- IWM iron condor: open, healthy
- PLTR put spread: open
- Flip Bot: no open positions
