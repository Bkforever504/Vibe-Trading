# Preregistration: MES VWAP Band Fade on Classified Range Days

Date: 2026-07-19
Status: frozen before running any simulation
Owner: Claude (research only, no execution)
Source: course-intelligence intake #3 (`research/COURSE_INTELLIGENCE_INTAKE_2026-07-19.md`)
and the Codex handoff's independently suggested "VWAP mean reversion on
classified range days" family.

## Hypothesis

On range days, price rejected at the intraday VWAP +/-1 sigma band tends to
revert to VWAP. On trend days the same fade fails. A causal range-day
classifier plus a band-rejection entry therefore has positive expectancy.

## Frozen Definitions

- VWAP: cumulative session volume-weighted typical price ((H+L+C)/3).
- Sigma: cumulative volume-weighted standard deviation of typical price
  around VWAP. Bands at VWAP +/- k sigma.
- Rejection: 1m bar high touches or exceeds the upper band and closes back
  inside (mirror at lower band).
- Trend-day (acceptance) filter: if 10 or more consecutive 1m closes occur
  outside either band before the signal, no trades for the rest of the day.
- Entries 09:45-12:00 ET only (skip first 15 minutes). One trade per day.
- Stop: 32 ticks (8 points). Target: touch of current VWAP (dynamic).
- Time stop: 60 minutes, exit at close. End-of-day flatten 15:55 ET.
- Same-bar stop-and-target counts as a stop (pessimistic).
- Costs: $1.24 commission + 1 tick slippage per side (~$4.98 round trip);
  stress at 2x.

## Frozen Configurations (4 total, no further variants)

Band multiplier k in {1.0, 1.5} x minimum rejection wick beyond the band
in {0, 2} ticks.

## Splits and Sequential Gates (identical to prior MES tests)

- Development: first 70% of sessions, three equal chronological regimes.
  Gate: positive expectancy in all three regimes.
- Selection: next 15%. Gate: positive expectancy, PF >= 1.20, positive at
  doubled costs.
- Final: last 15%. Only if selection passes. Gate: >= 30 trades, PF >= 1.20,
  positive at doubled costs, max drawdown <= $200.

## Explicit Limits

- The final window was consumed once by the ORB evaluation; a historical
  pass cannot alone promote this family. 30+ forward-simulation trades
  required regardless.
- The course's claimed 70-80% range-day hit rate is an unverified marketing
  number and carries no evidentiary weight.
- If gates fail: rejected under this spec, no rescue filters on this data.
- No execution of any kind is enabled by this work.
