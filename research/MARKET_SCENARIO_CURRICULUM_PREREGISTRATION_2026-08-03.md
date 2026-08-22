# Market Scenario Curriculum Preregistration

Date frozen: 2026-08-03

## Question

Can a policy trained only on prior SPY, QQQ, and IWM five-minute bars select
long, short, or abstain at fixed intraday checkpoints with positive unseen
directional expectancy after base, doubled, and tripled cost assumptions?

## Frozen Design

- Data: local SPY, QQQ, and IWM five-minute parquet caches.
- Checkpoints: 10:30, 11:00, 12:00, 13:00, 14:00, and 15:00 ET.
- Features: session VWAP, EMA 5/12 state, opening-range location, trailing
  point-in-time range regime, volume regime, and overnight gap state.
- Scenario key: symbol, checkpoint, trend state, opening-range state, and range
  regime.
- Entry: checkpoint bar open after features are computed from earlier bars.
- Exit: final close in the next 60 minutes.
- Actions: long, short, or abstain.
- Base round-trip cost: 4 bps of underlying notional. Stress tests use 8 and
  12 bps.
- Training window: 504 sessions.
- Test window: next 126 sessions, never used for that fold's policy.
- Locked final holdout: last 252 sessions, inspected once.
- A scenario is tradable in research only with at least 30 training episodes,
  positive base and doubled-cost expectancy, positive expectancy after the top
  5% of winners are removed, and at least a 50% training win rate.
- All other scenarios map to abstain.

## Review Gate

- At least five chronological folds.
- At least 100 out-of-sample trades.
- At least 60% of traded folds profitable.
- Positive aggregate base, doubled-cost, tripled-cost, and top-5%-removed
  out-of-sample expectancy.
- At least 30 locked-holdout trades.
- Positive locked-holdout base and doubled-cost expectancy.

## Authority

This trial is read-only. Passing permits human review only. It cannot alter bot
parameters, enable execution, or establish option profitability. Historical
option NBBO replay remains mandatory before an option strategy can use the
result as execution evidence.
