# Preregistration: MES Quote-Flow Edges (bbo-1s)

Date: 2026-07-19
Status: frozen before the bbo-1s data has been opened or analyzed
Owner: Claude (research only, no execution)
Data: `data/databento/mes_v0_bbo1s_2024-01-01_2026-07-19.dbn.zst`
(MES.v.0 1-second best bid/offer, purchased with Kenny's approval).

## Hypotheses (frozen)

H1. Quote-imbalance drift: sustained bid-size dominance at the top of book
precedes short-term upward price drift (and mirror for ask dominance).

H2 (diagnostic only, no gates): entry-time quote conditions (spread state,
imbalance direction) materially separate winners from losers in the frozen
5-minute gap ORB candidate's development/selection trades. Final-period
sessions are excluded because that window is consumed.

H3. Opening quote-pressure momentum: the cumulative quote imbalance of the
first five minutes predicts direction over the following session segment.

## Frozen Definitions

- Imbalance per second: (bid_size - ask_size) / (bid_size + ask_size).
- RTH only, 09:30-16:00 ET. Sessions with missing quote coverage excluded
  and reported.
- Execution realism: buy at ask, sell at bid (spread paid from the data),
  plus $1.24 commission per side. Stress: 2x commission plus 1 extra tick
  per side.
- MES 1 contract, $5/point, $1.25/tick.

## Frozen Configurations

H1 (2 configs): rolling 300-second mean imbalance crosses +/-0.35 (config
A) or +/-0.50 (config B) -> enter in the imbalance direction at the current
ask (long) or bid (short); exit at the opposite quote exactly 300 seconds
later. Non-overlapping positions, maximum 3 per day, signals 09:35-15:30,
forced exit by 15:55.

H3 (2 configs): mean imbalance 09:30:00-09:34:59 with absolute value
>= 0.25 -> enter at 09:35 in the imbalance direction at ask/bid. Stop 40
ticks on the mid path, target 1.5R (config A) or 2.0R (config B) on the
mid path, exits priced at bid/ask, flatten 15:55. One trade per day.

## Splits and Gates (H1 and H3)

Chronological 70/15/15 on available sessions (2024-2026 only; this window
overlaps the consumed OHLC final period, so any pass is historical evidence
only and can never alone promote).

- Development: three equal regimes; gate: positive expectancy in all three.
- Selection: positive expectancy, PF >= 1.20, positive at stressed costs.
- Final: >= 30 trades, PF >= 1.20, positive at stressed costs,
  max drawdown <= $200.

## Explicit Limits

- Four executable configs total plus one diagnostic. No further variants.
- Fail = rejected under this spec; no threshold tuning afterward.
- H2 output may motivate ONE new preregistration later; it may not be used
  to retroactively resurrect the ORB candidate on the same sample.
- No execution of any kind is enabled by this work.
