# Liquidity Sweep -> MSS/FVG -> Retest Audit

Date: 2026-08-18  
Status: retrospective public-rule replication; research only

## Mechanical Rule

1. Build completed five-minute bars from MES one-minute RTH data.
2. Declare prior-day high/low and the completed 09:30-09:45 opening range before they can be used.
3. Between 09:45 and 11:00 ET, require price to trade at least one tick through a declared level and close back across it.
4. Within six completed five-minute bars, require a close through the last three pre-sweep bars in the reversal direction.
5. The structure-break bar must have a body at least 0.50 times the mean range of the prior three bars and form a classic three-bar FVG of at least one tick.
6. Within six more bars, require a touch of the FVG midpoint and a close back in the reversal direction. The swept extreme cannot be invalidated.
7. Enter at the completed rejection-bar close. Stop one tick beyond the swept extreme. Target 2R. One MES contract and one trade maximum per session.
8. Model $4.98 baseline round-trip friction and $9.96 stress friction. Stop wins same-bar ambiguity.

## Evidence Standard

The full sample is split chronologically into 70% development, 15% selection, and 15% final periods. Every period is disclosed because this translation was created before a formal preregistration. Promotion requires at least 30 trades, positive expectancy, profit factor at least 1.20, and positive doubled-friction expectancy in all three periods.

The module has no broker imports, cannot submit orders, and cannot change an execution gate or risk budget.
