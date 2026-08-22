# Preregistration: MES Causal Impact-Replenishment Divergence

Date: 2026-08-10
Status: frozen before any strategy outcome or P&L was calculated
Execution: research only; no order-routing authority

## Claim Boundary

This is a bespoke hypothesis assembled for this repository. It is not claimed
to be globally novel, proprietary, or profitable. The test may reject it. A
historical pass would permit only later forward shadow observation, never a
Combine purchase or order submission.

## Mechanism

Short-horizon price changes usually respond to order-flow imbalance, with
impact varying inversely with available depth. A large flow shock that produces
far less price movement than its own trailing impact relationship predicts may
indicate resilient or hidden opposing liquidity. The strategy acts only when
the visible quote also replenishes against the shock and price confirms a
one-tick reversal after the measurement window closes.

The differentiator from the repository's rejected fixed-absorption rule is the
causal, session-local impact residual. The differentiator from its rejected
quote-imbalance rule is that quote state is confirmation, not the primary
signal.

Primary research basis:

- Cont, Kukanov, and Stoikov, *The Price Impact of Order Book Events*:
  https://arxiv.org/abs/1011.6402
- Bechler and Ludkovski, *Order Flows and Limit Order Book Resiliency on the
  Meso-Scale*: https://arxiv.org/abs/1708.02715
- Frey and Sandas, *The Impact of Iceberg Orders in Limit Order Books*:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1108485

These papers motivate the mechanism; they do not establish profitability in
MES or validate this implementation.

## Frozen Data

- Instrument: continuous front MES (`MES.v.0`), one contract.
- Source: Databento `GLBX.MDP3` BBO snapshots already cached at
  `data/databento/mes_v0_bbo1s_rth.parquet`.
- Period: 2024-01-01 through the cache endpoint, expected 2026-07-17.
- Session: 09:35:00 through 15:30:00 America/New_York.
- One quote per second, using the last valid BBO received in that second.
- Valid quote: positive bid, ask above bid, spread no wider than four MES
  ticks.
- Exclude known continuous-contract roll sessions, degraded dataset dates,
  weekends, and sessions with fewer than 700 valid 30-second buckets.

All available dates have been touched by other strategy families. Therefore
the result is explicitly a consumed-history diagnostic, not independent
validation.

## Frozen Feature

For each one-second quote, calculate Cont-style top-of-book order-flow
imbalance using the current and previous bid price/size and ask price/size.
Aggregate it into non-overlapping 30-second buckets.

For bucket `t`:

- `x_t = sum(OFI_t) / mean(top_book_depth_t)`
- `y_t = ending_mid_t - starting_mid_t`
- Fit a zero-intercept trailing impact coefficient from the prior 60 complete
  buckets only: `beta_t = sum(x*y) / sum(x^2)`.
- Standardize `x_t` using the prior 60 buckets only.
- `expected_t = beta_t * x_t`.
- `realized_fraction_t = sign(x_t) * y_t / abs(expected_t)`.

A completed bucket qualifies only when all are true:

1. The prior 60-bucket window is complete and `beta_t > 0`.
2. `abs(z_t) >= 2.5`.
3. `abs(expected_t) >= 0.50` MES points.
4. `0 <= realized_fraction_t <= 0.25`.
5. The ending one-tick-or-tighter quote imbalance opposes the flow by at
   least 0.10.
6. Signal time is from 10:05:00 through 15:19:59 ET.

## Frozen Confirmation And Entry

Observe, without trading, the first ten seconds after the signal bucket:

- the ending mid must move at least one tick opposite the flow shock;
- price may not extend more than two ticks in the shock direction;
- ending quote imbalance must remain neutral or oppose the shock;
- entry spread must be one tick or tighter.

Enter opposite the flow at the last valid quote before the ten-second
confirmation window ends. Long entries pay the ask; short entries receive the
bid. Confirmation data can never be used at an earlier timestamp.

## Frozen Exit And Costs

- Target: 12 ticks from executable entry.
- Stop: 8 ticks from executable entry.
- Time exit: 300 seconds after entry.
- Target and stop use executable opposite-side BBO prices.
- Stop is evaluated before target at each observation.
- Maximum two non-overlapping trades per session.
- Base commission: $2.48 round trip, in addition to observed spread.
- Stress: doubled commission plus one extra adverse tick on entry and exit.

No scaling, trailing stop, break-even move, news filter, trend filter, or
parameter alternative is permitted.

## Frozen Chronology And Gates

Eligible sessions are divided 60% development, 20% selection, and 20% final,
chronologically. Later stages remain unopened unless the prior stage passes.

Development requires:

- at least 40 trades;
- positive base and stressed expectancy;
- base profit factor at least 1.20;
- stressed maximum drawdown no greater than $500;
- positive stressed P&L in at least three of four chronological subperiods.

Selection and final each require:

- at least 20 trades;
- positive base and stressed expectancy;
- base profit factor at least 1.20;
- stressed maximum drawdown no greater than $500;
- five-session circular-block bootstrap probability of positive mean daily
  P&L at least 0.95.

Even if every historical gate passes, promotion is limited to a later frozen
forward-shadow protocol with at least 30 trades. Execution remains disabled.

## Locked Failure Rule

Any failed stage rejects this exact specification on these dates. Do not alter
the bucket, lookback, z-score, impact ratio, quote threshold, confirmation,
target, stop, hold, costs, or time window after viewing results. A materially
different future hypothesis requires a new data period and a new dated
preregistration.
