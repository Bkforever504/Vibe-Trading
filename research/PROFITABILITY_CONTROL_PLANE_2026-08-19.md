# Profitability Control Plane Preregistration

Date frozen: 2026-08-19

## Objective

The daily output is either a positive, cost-adjusted paper candidate or an
explicit cash decision. A daily trade and a daily profit are not requirements.

## Capital Rule

A candidate may beat cash only when all of the following are true:

1. The point-in-time signal and required data are current.
2. The strategy lifecycle is paper-approved by the existing review process.
3. At least 30 forward outcomes exist.
4. The strategy is compatible with the current regime.
5. Defined maximum loss and round-trip costs are available.
6. The lower confidence bound remains positive after costs and a one-sided,
   regime-weighted recent loss-error buffer.
7. One unit fits the candidate, cluster, and daily risk budgets.

Confidence scores, indicator counts, social-media claims, and retrospective
win rates cannot override a failed rule.

## Portfolio Rule

Only one candidate may consume risk in a correlated risk cluster. The default
caps are 0.25% of equity per candidate, 0.35% per cluster, and 0.50% per day.
The module cannot submit an order, promote a strategy, or enable live trading.

## Learning Rule

Every signal records the executable take, cash abstention, delayed entry,
opposite direction at equal risk, policy exit, and realized exit. Only
preregistered forward outcomes may change lifecycle state.

