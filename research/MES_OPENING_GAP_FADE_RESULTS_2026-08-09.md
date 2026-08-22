# MES Opening-Gap Failure/Fade Results - 2026-08-09

## Verdict

No configuration passed the historical stability gate. Nothing was promoted,
scheduled, or connected to Topstep execution.

The experiment evaluated 12 preregistered prior-close gap-fade configurations
on 589 eligible MES sessions from 2024-01-02 through 2026-07-17. It excluded
23 incomplete sessions, 20 sessions without a complete prior session, and 9
contract-roll boundaries.

## Best Diagnostic Row

`gap0p35_confirm5_reject0p25` had the broadest cross-year coverage:

- only 8 total trades;
- base costs: +$33.46 expectancy, 62.5% wins, PF 3.16;
- 2x costs: +$28.48 expectancy, 50.0% wins, PF 2.60;
- one-sided mean-test p-value: 0.1400 versus familywise alpha 0.00417; and
- no calendar year met its minimum sample requirement.

The positive point estimate is not evidence of a dependable edge. The sample
is too small, and the complete history is consumed research data.

## Topstep Diagnostic

Using the best row's 2x-cost daily outcomes, a 2,000-path circular block
bootstrap produced:

- 1 MES: 0% Combine pass, 0% MLL failure, 100% incomplete;
- 2 MES: 0% Combine pass, 0% MLL failure, 100% incomplete.

The low MLL failure rate is not a strength; the strategy trades too rarely to
approach the profit target.

## Decision

- Keep execution disabled.
- Do not buy a Combine for this strategy.
- Do not expand the grid after seeing these outcomes.
- Preserve the report as a failed/insufficient hypothesis.
- Require a materially different information source for the next challenger,
  rather than another opening-price transformation.

Machine-readable report: `data/mes_opening_gap_fade_results.json`.
