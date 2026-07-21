# Preregistration: MES Quote-Imbalance Exhaustion

Date: 2026-07-20
Status: frozen before selection or final outcomes are opened
Execution: research only; no order-routing authority

## Why This Is A New Test

The preregistered quote-imbalance momentum family lost in all three development
regimes. Its selection and final periods were never evaluated because the
development gate failed. This test asks one opposite, mechanistic question:
does an extreme, sustained top-of-book imbalance represent short-horizon
exhaustion rather than continuation?

The failed development result motivated the direction change. It may not be
used as independent validation. The first honest gate is the untouched BBO
selection period.

## Frozen Signal And Execution

- Instrument: one MES contract.
- Data: Databento `GLBX.MDP3`, `MES.v.0`, `bbo-1s`.
- Session: 09:35:00 through 15:30:00 ET; flatten no later than 15:55 ET.
- Imbalance: `(bid_size - ask_size) / (bid_size + ask_size)`.
- State: 300-observation rolling mean imbalance.
- Trigger: the rolling mean crosses outward through `+0.10` or `-0.10`.
- Direction: fade the imbalance. `+0.10` enters short; `-0.10` enters long.
- Entry: long at the observed ask; short at the observed bid.
- Risk: hard 20-tick stop evaluated on the mid-price path.
- Exit: stop, otherwise the opposite executable quote 300 seconds after entry.
- Frequency: non-overlapping positions, maximum three trades per session.
- No target, trend, ORB, VWAP, gap, VIX, time-bucket, or news filters.
- No threshold, stop, horizon, or session sweep.

## Costs

- Base: actual observed spread plus $1.24 commission per side.
- Stress: observed spread plus doubled commission and one extra tick per side.

## Frozen Chronology

Use the same available-session ordering as the prior BBO study:

- First 70%: consumed development/discovery; outcomes are not a gate.
- Next 15%: untouched selection, evaluated first.
- Final 15%: inaccessible unless selection passes every gate unchanged.

## Selection And Final Gates

Each opened stage must satisfy all of the following:

- At least 30 trades.
- Positive expectancy at base costs.
- Profit factor at least 1.20 at base costs.
- Positive expectancy under stressed costs.
- Maximum drawdown no greater than $200.
- No session loss worse than $100.
- No best-day consistency violation above 50% of cumulative positive P&L.

Selection failure permanently rejects this specification on this dataset and
keeps final outcomes sealed. Final failure also rejects it. No post-result
threshold adjustment or third calibration round is allowed.

## Promotion Boundary

Even a historical pass remains research-only because the BBO period overlaps
previously consumed OHLC history. Promotion would additionally require at least
30 later chronological NinjaTrader Sim101 outcomes, realistic fill evidence,
zero prop-rule violations, and explicit human approval. The scheduled MES task
must remain disabled throughout this test.
