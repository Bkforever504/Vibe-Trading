# MES Causal Impact-Replenishment Divergence Results

Date: 2026-08-10
Preregistration: `research/MES_CAUSAL_IMPACT_REVERSAL_PREREGISTRATION_2026-08-10.md`
Artifact: `data/mes_causal_impact_reversal_results.json`

## Verdict

Rejected as historically infeasible and unprofitable at the frozen
specification. It is not an edge and must not be traded, widened, or promoted.

## Exact Result

- Source: Databento MES BBO snapshots converted to one-second valid quotes and
  Cont-style 30-second order-flow imbalance.
- Period: 2024-01-02 through 2026-07-17.
- Eligible complete sessions: 618.
- Split: 370 development / 124 selection / 124 final sessions.
- Confirmed candidates across the complete period: 1.
- Development trades: 1.
- Base: -$7.48 total and expectancy, 0% win rate.
- Stress: -$12.46 total and expectancy, 0% win rate.
- Exit: time stop.
- Development gate: failed.
- Selection and final: correctly unopened.
- Topstep simulation: correctly not run.
- Orders submitted: 0.

The intersection of an extreme causal OFI shock, weak realized impact,
opposing quote replenishment, one-tick spread, and delayed reversal
confirmation was too rare to support inference. The one observation was also
negative. Changing the frozen thresholds now would be outcome-driven tuning.

## What Was Learned

The architecture is more defensible than another price-pattern grid because it
models a causal market mechanism. BBO snapshots are nevertheless a weak proxy
for the actual mechanism. They cannot separate new limit orders from
cancellations, observe replenishment beyond the best quote, or identify hidden
liquidity directly. Those missing measurements likely matter more than another
threshold search.

## Locked Next Step

Do not rerun or relax CIRD on these dates. A future test requires genuinely new
post-preregistration data containing at least top-five depth updates, trades,
and source timestamps. The next experiment must:

1. pass the existing TopstepX microstructure data-quality protocol;
2. measure event-based OFI, depth replenishment, cancellation/addition rates,
   spread recovery, and realized impact without future returns;
3. freeze a small hypothesis family before opening outcomes;
4. use chronological forward evaluation with executable fills, doubled costs,
   and exact Topstep risk simulation;
5. remain shadow-only until at least 30 later forward trades pass.

No historical result here supports a profitability, market-beating, or novelty
claim.
