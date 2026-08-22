# Swing Exit Overlay Preregistration

Date: 2026-08-13
Status: frozen before exit-overlay outcomes are computed
Mode: research only; no execution authority

## Entry and Portfolio Rules

Use the unchanged monthly equal-weight top-five technology momentum baseline
from `SWING_RISK_OVERLAY_PREREGISTRATION_2026-08-13.md`. Entries occur at the
next session open. Maximum scheduled holding period remains 20 sessions.

## Frozen Exit Variants

No parameter sweep is permitted:

1. `fixed_20d`: unchanged exit at the twentieth session close.
2. `initial_stop_2_5atr`: initial stop at entry minus 2.5 times the completed
   20-session ATR. Stop remains fixed.
3. `chandelier_3atr`: initial stop at entry minus 3.0 ATR. After each completed
   session, the next session's stop is raised to the highest completed close
   since entry minus 3.0 times the ATR known at that completed close.
4. `asymmetric_profit_lock`: initial stop at entry minus 2.5 ATR. Once a
   completed close reaches entry plus 3.0 initial ATR, the next session's stop
   is raised to highest completed close minus 1.5 current ATR.

Gap execution is conservative: if a session opens below the active stop, exit
at that open; otherwise, if its low touches the stop, exit at the stop. Stops
are never updated from a session's high/close until after that session ends.

## Costs and Chronology

- Ordinary round-trip cost: 10 bps.
- Stress round-trip cost: 30 bps.
- Only fully resolved 20-session holding windows are scored.
- Development: 2015-2022.
- Selection diagnostic: 2023-2025.
- Variant-sealed but previously aggregated diagnostic: 2026 through 2026-07-20.

## Success Gates

Relative to `fixed_20d`, a candidate must:

- Increase 2023-2025 ending equity.
- Reduce 2023-2025 maximum drawdown by at least 20%.
- Maintain positive 30-bps expectancy in every period.
- Maintain positive expectancy after removing the best 1% in every period.
- Have a positive development bootstrap lower bound.
- Produce at least 25 active periods in 2023-2025.

Passing allows shadow-only forward testing, never immediate execution.
