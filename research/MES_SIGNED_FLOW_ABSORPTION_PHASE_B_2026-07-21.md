# Preregistration: MES Signed-Flow Absorption Phase B

Date: 2026-07-21
Status: frozen after Phase A quality passed and before any strategy outcome was calculated
Execution: research only; no order-routing authority

## Outcome-Blind Inputs Used

Phase A contained 22,080 non-overlapping one-minute windows across 61 complete
sessions. Relevant distribution landmarks were:

- aggressive volume p90: 4,992 contracts;
- absolute signed imbalance p90: 0.398471;
- absolute one-minute mid displacement p25: 0.50 MES points.

No forward return, trade outcome, stop, target, or P&L was opened to select
these values.

## Frozen Signal

A completed 60-second window qualifies when all are true:

1. total classified aggressive volume is at least 5,000 contracts;
2. absolute signed-volume imbalance is at least 0.40;
3. absolute mid-price displacement during the window is at most 0.50 points;
4. the window ends no later than 15:25 ET.

This represents unusually large and one-sided aggressive flow that did not
move price materially. At the first BBO observation at or after the completed
window, take the opposite direction of the aggressive imbalance. Hold exactly
five minutes and exit at the first BBO observation at or after that time.

- Long entries pay the ask and exit at the bid.
- Short entries receive the bid and cover at the ask.
- Maximum three signals per session.
- Signals cannot overlap; later signals while a position is open are skipped.
- No stop, target, scaling, or parameter alternatives are allowed.

## Costs and Chronology

- Base: observed BBO spread plus $2.48 round-trip commission.
- Stress: base spread, one additional tick adverse on entry and exit, and
  $4.96 round-trip commission.
- Sessions are split chronologically 70/30 after exclusions.
- Development is opened first. Continue to the final segment only if
  development has at least 30 trades, positive expectancy, profit factor at
  least 1.20, and positive stressed expectancy.
- A final pass requires at least 15 trades, positive expectancy, profit factor
  at least 1.20, and positive stressed expectancy.

Failure ends this family. Parameters will not be retuned on these dates.
Passing remains discovery evidence only and cannot enable NinjaTrader or any
live execution. Promotion still requires 30 later chronological Sim101
outcomes, realistic fill evidence, zero rule violations, adversarial review,
and explicit human approval.
