# MES Quote-Imbalance Exhaustion Results

Date: 2026-07-20
Execution state: research only; MES scheduled task disabled

## Frozen Test

The specification was frozen before opening selection outcomes in
`MES_QUOTE_EXHAUSTION_PREREGISTRATION_2026-07-20.md`.

- One MES contract.
- Fade an outward crossing of the 300-observation mean BBO imbalance through
  `+/-0.10`.
- Enter at the observed bid/ask.
- Hard 20-tick stop.
- Exit after 300 seconds if not stopped.
- Maximum three non-overlapping trades per session.
- Base and doubled-cost-plus-one-tick stress models.
- No parameter sweep.

The first 70% development period was explicitly treated as consumed discovery
and not reopened as validation. Selection was the first honest gate. The final
15% was code-sealed unless selection passed every frozen requirement.

## Untouched Selection Result

| Metric | Base costs | Stressed costs |
|---|---:|---:|
| Trades | 52 | 52 |
| Trading days | 38 | 38 |
| Total P&L | -$380.21 | -$639.17 |
| Expectancy | -$7.31 | -$12.29 |
| Win rate | 40.38% | 23.08% |
| Profit factor | 0.41 | 0.23 |
| Maximum drawdown | $397.77 | $646.75 |
| Worst session | -$63.69 | -$78.63 |
| Hard stops | 15 | 15 |

Failed gates:

- Positive expectancy.
- Profit factor at least 1.20.
- Positive stressed expectancy.
- Maximum drawdown no greater than $200.
- Best-day consistency could not be satisfied because cumulative P&L was
  negative.

The $100 session-loss boundary was not breached, but risk compliance without
positive expectancy is not an edge.

## Final Holdout

The final 93 sessions remain unopened. The result JSON contains only their
count and the reason `sealed_until_selection_passes`; it contains no final
performance statistics.

## Verdict

Rejected. Direct top-of-book quote imbalance is not a profitable MES signal in
the tested continuation or exhaustion direction. Retuning the threshold,
holding period, or stop on these outcomes would consume the failure and create
selection bias.

This result narrows the problem usefully: the next strategy family should not
depend on BBO imbalance direction alone. A legitimate next research branch must
use a different information source or mechanism, such as signed trade flow and
absorption, scheduled-event behavior, or a later forward-only auction setup.

## Richer-Data Cost Check

Estimate-only Databento queries were run after the verdict; no data was bought:

- MES trades, 2024-01-01 through 2026-07-19: approximately $288.35.
- MES MBP-1, same period: approximately $677.80.
- MES trades, 2026 year-to-date: approximately $80.04.
- MES trades, 2025 second half: approximately $50.58.
- MES trades, 2025 Q4: approximately $29.33.

The full-history feeds are not justified. A small trade-print discovery slice
could be considered only after a new signed-flow/absorption hypothesis is
preregistered, with explicit purchase approval and later forward-only evidence.

## Confidence

- Data and chronology integrity: 9/10.
- Reproducibility: 9/10.
- Confidence this frozen exhaustion setup is not ready: 9/10.
- Confidence BBO imbalance direction alone is a deployable edge: 1/10.
- Profitability confidence for the current Topstep bot: 2/10.

No Topstep Combine purchase or MES execution is justified by this result.
