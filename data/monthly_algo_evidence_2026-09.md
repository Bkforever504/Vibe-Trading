# Algorithm Operations Evidence Packet - 2026-09

Generated: 2026-09-04T21:20:26.014947Z

## Authority

- Execution enabled: `False`
- Can submit orders: `False`
- Orders submitted: `0`
- Promotion authority: `blocked`

## Strategy Lifecycle

| Lane | State | N | Stable reviews | Paper review eligible | Reasons |
|---|---|---:|---:|---|---|
| mes_reopen_drift | suspended | 438 | 0/2 | False | decay_suspend, retrospective_only_independent_bootstrap_crosses_zero |
| qqq_mean_reversion | research_only | 136 | 12/2 | False | development_only_failed_experiment_wide_multiple_testing |
| trend_participation | collecting | 0 | 0/2 | False | fewer_than_30_resolved_observations, bootstrap_lower_bound_not_positive, placebo_insufficient_n, decay_insufficient_n |
| volatility_premium | suspended | 85 | 0/2 | False | bootstrap_lower_bound_not_positive, placebo_fail, decay_watch |

## Edge Evidence

| Lane | N | Mean PnL | Profit factor | Placebo | Decay | Bootstrap 90% |
|---|---:|---:|---:|---|---|---|
| mes_reopen_drift | 438 | 12.2643 | 1.34 | pass | suspend | [3.5941, 20.7837] |
| qqq_mean_reversion | 136 | 51.9018 | 2.1421 | pass | stable | [26.8263, 77.0041] |
| trend_participation | 0 | n/a | n/a | insufficient_n | insufficient_n | [n/a, n/a] |
| volatility_premium | 85 | -17.5176 | 0.1732 | fail | watch | [-30.4129, -6.4471] |

## Portfolio Dependence

Status: `cash_only`

| Pair | Overlap | Return corr | Loss-event corr | Joint-loss lift | Status |
|---|---:|---:|---:|---:|---|
| mes_reopen_drift / qqq_mean_reversion | 2 | n/a | n/a | n/a | insufficient_overlap |
| mes_reopen_drift / trend_participation | 0 | n/a | n/a | n/a | insufficient_overlap |
| mes_reopen_drift / volatility_premium | 0 | n/a | n/a | n/a | insufficient_overlap |
| qqq_mean_reversion / trend_participation | 0 | n/a | n/a | n/a | insufficient_overlap |
| qqq_mean_reversion / volatility_premium | 0 | n/a | n/a | n/a | insufficient_overlap |
| trend_participation / volatility_premium | 0 | n/a | n/a | n/a | insufficient_overlap |

## Execution Reality

- Status: `insufficient_forward_fills`
- Forward fill samples: `3`
- Modeled mid-to-executable gap: `9.6042%`
- Observed average adverse fill versus signal ask: `0.0%`
- Observed p95 adverse fill versus signal ask: `0.0%`

## Reproducibility

- Configuration fingerprint: `4d5856ede25d5dda6df6d460af4ea03ffebf0c6eca087dfbab47c7f7ea3c81c2`
- Operational SLO: `ok`

This packet is descriptive. It cannot place orders, promote a strategy, reactivate a suspended strategy, or increase risk.
