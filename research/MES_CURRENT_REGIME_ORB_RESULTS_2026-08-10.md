# MES Current-Regime ORB Search Results - 2026-08-10

## Verdict

Restricting the MES ORB/pullback search to 2024-2026 did not produce a
selection survivor. The strategy family remains ineligible for Topstep
Practice execution or a Trading Combine purchase.

## Corrected Search

The final diagnostic corrected two integrity problems before recomputation:

1. opening-gap filters now block quarterly contract-roll boundaries; and
2. finalist selection deduplicates exact development trade paths, preventing
   equivalent filter labels from occupying multiple finalist slots.

The development grid was evaluated across four local workers. Parallelism
changed runtime only; results were deterministically re-sorted before finalist
selection.

Results:

- effective period: 2024-01-02 through 2026-07-17;
- 641 trading dates;
- 448 development, 96 selection, and 97 diagnostic final dates;
- 16,320 executable-only configurations;
- 58 development survivors;
- 33 unique development trade paths;
- 25 duplicate behaviors removed; and
- **0 selection survivors**.

The least-negative selection row was a 5-minute pullback with 1-point
breakout, 2R target, 80-tick stop, and EMA20 filter:

- 14 selection trades;
- base expectancy -$1.77, PF 0.9708;
- doubled-cost expectancy -$5.95, PF 0.9060.

No final-period evaluation was authorized because nothing passed selection.

## Evidence Label

This is a consumed-history diagnostic, not independent validation. The output
records `diagnostic_consumed_period_not_independent_validation`,
`execution_enabled: false`, and `can_submit_orders: false`.

Machine-readable report:
`data/mes_strategy_search_2024plus_rollsafe_unique_diagnostic.json`.

## Related Mean-Reversion Test

The preregistered opening-gap failure/fade family also produced zero historical
stability survivors. Its best cross-year row had only eight trades and a
familywise-insignificant 2x-cost result. Exact 1-2 MES Combine diagnostics had
0% pass rates. See `research/MES_OPENING_GAP_FADE_RESULTS_2026-08-09.md`.

## Decision

- Do not route ORB, pullback, or opening-gap fade to Topstep Practice.
- Do not increase contracts to force the Combine target.
- Do not reopen the 2024-2026 final history for more parameter tuning.
- Collect new MES quote, trade, and explicit DOM evidence and formulate a
  materially new microstructure hypothesis only after the collection gate.
