# Verifiable Edge Status

As of 2026-08-17, no newly tested intelligence policy qualifies as a
forward-validated trading edge. This is a fail-closed evidence record, not a
profitability claim.

## MES Intelligence Meta-Policy

- Frozen specification: `INTELLIGENCE_EDGE_META_POLICY_PREREGISTRATION_2026-08-17.md`
- Result: `data/intelligence_edge_meta_policy_results.json`
- Evidence: 105 trades on 105 sessions from 2022-01-03 through 2026-07-17.
- Baseline expectancy: -$6.42 per trade.
- Baseline profit factor: 0.82.
- Baseline maximum drawdown: -$1,231.76.
- Stress expectancy: -$8.92 per trade.
- Verdict: `rejected_historical_candidate`.

The exact policy is frozen as rejected and must not be retuned on the same
dates and presented as independent evidence.

## Confirmed-Momentum Delayed Option Entry

- Frozen specification: `CONFIRMED_MOMENTUM_DELAYED_ENTRY_SPEC_2026-08-17.md`
- Result: `data/confirmed_momentum_delayed_entry_results.json`
- Evidence: 584 executable ask-to-bid replays on 22 dates.
- Baseline expectancy: -5.33% per trade.
- Baseline profit factor: 0.70.
- Stress expectancy: -6.83% per trade.
- Verdict: `historical_candidate_rejected`.

This demonstrates that the previously observed positive first-mark conditional
statistic was not executable after waiting for confirmation. It must not be
used as an entry edge.

## Operational Authority

- Neither result can submit orders.
- Neither result can enable paper or live execution.
- The Topstep intelligence gate remains without a forward-validated edge.
- Future candidates must be frozen before testing, use causal timestamps and
  executable prices, survive cost stress and winner-removal tests, and then
  pass on dates collected after their specification.
