# MES Signed-Flow Forward Protocol

Date: 2026-07-21
Status: frozen after the zero-candidate Phase B result
Cost authority: none
Execution authority: none

## Why This Exists

The Q4 trade-print slice proved that signed flow can be measured accurately,
but the first preregistered marginal-threshold conjunction was infeasible.
That historical period is now consumed. Searching looser combinations on it
would turn the learning loop into an overfitting loop.

## Stage 1: New Outcome-Blind Sessions

Collect at least 30 complete sessions dated after 2025-12-31. This stage logs:

- aggressive buy and sell volume by non-overlapping minute;
- signed imbalance;
- contemporaneous mid displacement;
- spread, quote age, and missing-data diagnostics;
- joint feature-density counts and volume-conditioned displacement bands.

It does not log future prices, simulated entries, or P&L. The learner may
propose challenger definitions, but it cannot change the champion, route an
order, or purchase data. Any paid-data action needs separate human approval.

After 30 sessions, freeze at most one challenger with an observed frequency of
roughly one to three non-overlapping signals per day. The definition must use
only contemporaneous joint distributions and must be written before Stage 2.

## Stage 2: Later Sim101 Validation

Evaluate the frozen challenger on at least 30 still-later chronological trades
in NinjaTrader Sim101. Use observed bid/ask fills, conservative commission,
one-tick-per-side stress, a maximum of three trades per day, and Topstep rule
checks.

Promotion review requires all of the following:

- at least 30 resolved trades;
- positive base and stressed expectancy;
- base profit factor at least 1.30;
- maximum drawdown no greater than $200;
- zero daily-loss, session, or consistency-rule violations;
- no single trade supplies more than 25% of total net profit;
- adversarial code/data review finds no look-ahead, timestamp, roll, or fill
  defect;
- explicit human approval.

The learner records mistakes and proposes challengers. It never edits live
risk, promotes itself, spends credits, or enables the disabled MES task.
