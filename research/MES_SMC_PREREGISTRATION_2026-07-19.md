# Preregistration: MES Liquidity-Sweep Fade and Fair-Value-Gap Continuation

Date: 2026-07-19
Status: frozen before running any simulation
Owner: Claude (research only, no execution)

## Hypotheses

1. Liquidity-sweep fade: when price breaks the prior session's high (or low)
   and quickly reclaims it, the move was a stop run and price tends to revert.
2. Fair-value-gap continuation: a three-bar imbalance on 5-minute bars marks
   initiative flow; a retrace into the gap midpoint tends to continue in the
   gap direction.

These are the mechanical cores of the ICT/SMC "liquidity sweep" and "FVG"
concepts. Social popularity is high; published systematic evidence is thin.
This test decides with data, not marketing.

## Frozen Configurations (6 total, no further variants)

Common: MES 1 contract, corrected Databento RTH CSV, one trade per day,
entries 09:35-12:00 ET only, 40-tick stop, full target/stop exits,
end-of-day flatten 15:55 ET, same-bar stop-and-target counts as a stop
(pessimistic). Costs: $1.24 commission + 1 tick slippage per side
(~$4.98 round trip); stress at 2x.

Sweep fade (2): break of prior-day high/low by >= 2 ticks, 1m close back
inside within 15 minutes, fade at that close. Reward/risk 1.5 and 2.0.

FVG continuation (4): 5m three-bar imbalance, minimum gap 4 or 8 ticks,
formed 09:30-12:00, entry at gap midpoint on first touch. Reward/risk 1.5
and 2.0.

## Splits and Sequential Gates (same architecture as the ORB search)

- Development: first 70% of sessions, three equal chronological regimes.
  Gate: positive expectancy in all three regimes.
- Selection: next 15%. Gate: positive expectancy, profit factor >= 1.20,
  positive expectancy at doubled costs.
- Final: last 15%. Evaluated only if selection passes. Gate: >= 30 trades,
  PF >= 1.20, positive at doubled costs, max drawdown <= $200.

## Explicit Limits

- The final 15% window was already consumed once by the ORB family
  evaluation. A historical pass here is therefore weaker evidence and can
  never by itself promote this family. Promotion additionally requires 30+
  forward-simulation trades.
- If gates fail, the family is recorded as rejected under this spec. No
  filters, no re-parameterization on this dataset.
- No execution of any kind is enabled by this work.
