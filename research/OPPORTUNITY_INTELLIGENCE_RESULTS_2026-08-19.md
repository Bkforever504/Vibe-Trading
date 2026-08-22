# Opportunity Intelligence Baseline Results

Run date: 2026-08-19

## Implementation

The daily read-only pipeline now covers all ten requested controls:

1. Regime-aware lane allocation with explicit cash.
2. Existing options gate counterfactual attribution.
3. Seeded placebo testing.
4. Recent edge-decay monitoring.
5. Synchronized moving-block portfolio simulation.
6. Quote-based execution policy A/B proxies.
7. Append-only accepted and rejected opportunity records.
8. Expanding point-in-time probability calibration.
9. Lower-confidence-bound research weighting.
10. Source freshness, parsing, and no-order operational invariants.

The scheduled task `Opportunity-Intelligence-Pipeline` runs at 4:20 PM CT on
weekdays. Its end-to-end scheduler test completed with result code 0.

## Measured baseline

| Lane | Observations | Mean PnL | Profit factor | Placebo | Decay | Research weight |
|---|---:|---:|---:|---|---|---:|
| QQQ mean reversion | 136 | $51.90 | 2.14 | pass | stable | 35% |
| MES reopen drift | 438 | $12.26 | 1.34 | pass | suspend | 0% |
| Volatility premium | 21 | -$30.29 | 0.14 | fail | insufficient | 0% |
| Trend participation | 0 | n/a | n/a | insufficient | insufficient | 0% |
| Cash | n/a | $0 | n/a | n/a | n/a | 65% |

QQQ's 90% moving-block mean interval was $26.83 to $77.00 per $10,000
development trade. This remains development-only evidence and did not pass the
experiment-wide multiple-test correction, so the 35% figure is a research
weight, not a position size or promotion.

MES passed the long-run sign-flip placebo test, but its latest 20 observations
averaged -$41.73 versus +$14.85 previously. The frozen decay rule therefore
suspended it despite positive full-sample statistics. This is the intended
behavior: a historical edge cannot override current deterioration.

Options demonstrate why win rate is not enough. The 21 resolved shadow
outcomes won 71.4% of the time but produced -$30.29 average PnL and a 0.14
profit factor because the losses were much larger than the wins.

## Execution baseline

Twenty-four point-in-time option candidates had both executable and midpoint
credits. Average executable credit was $0.3425 versus a $0.3667 midpoint, a
$0.0242 gap. Patient and escalating values are interpolation proxies only;
policy-specific fill outcomes are still required before selecting an order
policy.

## Operations and authority

- All five required source artifacts existed, parsed, and were fresh within 48
  hours.
- Every current rejected lane was written to the opportunity ledger.
- `execution_enabled`, `can_submit_orders`, and `orders_submitted` remain false,
  false, and zero.
- No broker integration or order method exists in the pipeline.
- No production strategy, gate, or size was changed.

The baseline report is `data/opportunity_intelligence_report.json`; the
append-only record is `data/opportunity_intelligence_ledger.jsonl`.
