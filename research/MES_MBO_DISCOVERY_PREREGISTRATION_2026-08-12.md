# MES Market-by-Order Discovery Preregistration

Date: 2026-08-12
Status: frozen before opening the MBO data
Authority: research only; no execution or routing authority

## Purpose

Test whether order-level liquidity response contains information absent from the
already-rejected BBO-imbalance and signed-trade-flow families. The first session
is a data-quality and feature-feasibility pilot, not profitability evidence.

## Data

- Provider: Databento
- Dataset: `GLBX.MDP3`
- Schema: `mbo`
- Symbol: `MES.v.0`
- Discovery session: 2026-07-15 UTC
- The request includes the complete UTC day so the initial MBO snapshot can be
  consumed before regular-hours measurements.

## Frozen Feature Families

1. **Depletion and replenishment:** resting size removed by aggressive trading,
   followed by same-side additions at the affected price within 1, 5, and 15
   seconds.
2. **Cancel/add pressure:** bid-side versus ask-side cancelled and added size in
   non-overlapping 5-second windows.
3. **Absorption efficiency:** signed aggressive volume divided by subsequent
   mid-price displacement, reported only when spread and book state are valid.
4. **Queue resilience:** time required for displayed size at an affected best
   price to recover 50% and 100% of its pre-trade level.

## Phase A Gates

- Snapshot is observed before feature measurement.
- Sequence numbers are monotonic within channel and gaps are reported.
- At least 99% of regular-hours events have recognized actions and sides.
- Reconstructed best bid is strictly below best ask whenever both exist.
- At least 95% of 5-second windows have valid book state.
- No future return, trade P&L, threshold selection, or strategy comparison is
  permitted in Phase A.

## Cost Guard

- Estimate before download.
- Hard request cap: $5.00.
- Reconstructed available credits: $23.45.
- Minimum reserve after download: $15.00.
- No card charge is authorized.

## Next Boundary

Only if Phase A quality gates pass may one outcome hypothesis be frozen for a
separate discovery sample. Any promising discovery requires a later untouched
sample and cost-stressed execution model. No result from this session can
enable Topstep, broker, paper, or live orders.
