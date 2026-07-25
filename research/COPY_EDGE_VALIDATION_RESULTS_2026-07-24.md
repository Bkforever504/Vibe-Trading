# Copy-Edge Validation Results - 2026-07-24

## Decision

Neither public strategy family earned promotion, shadow scheduling, or access
to an execution gate.

- COPY-MES-FBD-01: rejected in development.
- COPY-SPY-FT-01: insufficient evidence in development.
- MES and SPY selection/final periods remained sealed because no development
  candidate met its gate.
- No option P&L was inferred from underlying SPY bars.
- No live, paper, risk, scheduler, or order-routing setting changed.

## COPY-MES-FBD-01

### Data and controls

- MES continuous one-minute Databento bars.
- 1,148 audited RTH sessions, 2022-01-03 through 2026-07-17.
- 108 preregistered configurations.
- Levels: prior-day high/low and 30-minute opening-range high/low.
- Signal: first excursion, reclaim within a fixed window, fixed acceptance
  bars, and next-bar entry.
- One earliest qualifying trade per session.
- Stop-first resolution when stop and target occur in the same minute.
- Explicit commission and two-sided slippage.

### Result

- Development period: 688 sessions, 2022-01-03 through 2024-09-13.
- Development survivors: 0 of 108.
- Selection configurations evaluated: 0.
- Final configurations evaluated: 0.

The best near misses were not narrow. They worked in the first two development
regimes and collapsed in the third:

- Best worst-regime expectancy: -$7.50 per trade.
- Other top worst-regime expectancies: roughly -$7.81 to -$10.44.
- Third-regime profit factors among top near misses: approximately 0.52-0.64.
- Worst drawdown among the broad top candidate: $1,049.05.

This is regime failure, not a cost-only failure. Retuning against the third
development regime would be post-hoc optimization, so the family is rejected
as specified.

Machine-readable report:
`data/mes_failed_breakdown_results.json`

## COPY-SPY-FT-01

### Data and controls

- SPY one-minute IEX bars.
- 1,137 RTH sessions, 2022-01-03 through 2026-07-17.
- 1,184 point-in-time first-touch rejection events.
- 144 preregistered configurations.
- Levels: prior-day, premarket, and whole-dollar.
- Filters: one-minute RSI extreme and three/five-minute approach speed.
- Next-bar entry, stop-first same-minute resolution, one earliest event daily.
- One and two times estimated underlying slippage were available to later
  gates, but no candidate reached those gates.

### Result

- Development period: 682 sessions, 2022-01-03 through 2024-09-19.
- Development survivors: 0 of 144.
- Selection configurations evaluated: 0.
- Final configurations evaluated: 0.

The leading watch item was:

- Prior-day levels.
- RSI extreme 75/25.
- 1.5 reward/risk.
- No minimum approach-speed threshold.
- Regime expectancies: +0.088R, +0.2714R, +0.403R.
- Regime trades: 8, 13, 4.
- Regime profit factors: 1.141, 1.633, 2.133.

The signs are encouraging, but 25 total development trades spread as 8/13/4
are far below the 20-trades-per-regime gate. The correct classification is
insufficient evidence, not a passing edge. Selection and final data remain
sealed.

Machine-readable report:
`data/spy_first_touch_results.json`

## Bugs caught before acceptance

1. Insufficient RSI history initially became zero instead of unknown. It now
   fails closed and has a regression test.
2. Initial SPY split boundaries used signal dates rather than all RTH sessions.
   They now use every available RTH session and have a regression test.
3. MES diagnostic JSON initially could not serialize time fields. Output now
   serializes deterministically and has a regression test.

## Confidence

- Confidence MES failed-breakdown should not proceed as specified: 9/10.
- Confidence SPY first-touch is proven: 2/10.
- Confidence SPY prior-day first-touch deserves passive evidence collection:
  6/10.
- Confidence either family is ready for options or funded execution: 0/10.

## Next honest step

Do not broaden thresholds or inspect the sealed periods.

The SPY prior-day first-touch pattern can be reconsidered only after one of
these independent evidence additions:

1. More point-in-time history from a consolidated feed.
2. A preregistered forward-shadow log reaching at least 30 resolved signals.
3. Historical option minute NBBO before making any claim about 0DTE returns.

The existing passing momentum and turn-of-month lanes remain more credible than
either copied family.
