# Wolves/BBR tournament preregistration

This is a historical hypothesis test only. It cannot change ranking, alerts, sizing, or execution.

- Markets: SPY and QQQ.
- Bars: 5m and 15m; no 3m promotion lane.
- Families: `levels` (prior-session level break) and `full` (same break plus close above/below 200 EMA and 13/48 EMA direction).
- Entry: next-bar open after a confirmed close through the level.
- Stop: prior bar extreme; target: 2R; maximum hold: 60 minutes; fixed notional and conservative same-bar stop precedence.
- Costs: baseline and doubled friction; report trades, expectancy, profit factor, and chronological behavior.

The source material mentions PMH/PML and YDH/YDL, but the exact videos were not independently transcribed. This first pass uses completed prior calendar-month levels and prior-session levels, but cannot establish the named strategy. A follow-up must freeze retest behavior, EMA-ladder exit, and option-contract feasibility before any forward-shadow promotion.
