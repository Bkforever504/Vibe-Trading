# MNQ SMT Evidence Regime Labeler v1

- Status: frozen
- Frozen: 2026-08-24, before the first promotion-eligible 2026-08-25 session
- Scope: evidence stratification only; never changes an entry, exit, or grade
- Source: Databento `GLBX.MDP3` raw MNQ `ohlcv-1m`

At each frozen plan's actionable timestamp, aggregate complete five-minute
bars and select the latest 24 bars (two regular-session hours, though the
window may include overnight bars near the open).

1. Directional efficiency = `abs(last_close-first_close) / sum(abs(close_t-close_t-1))`.
   Label `trend` when efficiency is at least `0.35`; otherwise label `chop`.
2. Realized volatility = sample standard deviation of the 23 log returns,
   annualized by `sqrt(78*252)`. Label `high_vol` when it is at least `0.22`;
   otherwise label `low_vol`.
3. Fewer than 24 valid positive closes fails the regrade closed.

Every qualified outcome therefore has exactly one trend/chop tag and exactly
one high-vol/low-vol tag. These labels measure coverage only. They cannot be
used to select or suppress an MNQ-family signal without a new preregistration.

- `execution_enabled=false`
- `can_submit_orders=false`
