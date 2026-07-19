# MES Final-Half-Hour Momentum Preregistration

Registered: 2026-07-19, before running this strategy on the Databento sample.

## Hypothesis

The direction of the first 30-minute MES return contains information about the
direction of the final 30-minute return. Trade only the final half hour in the
same direction as the opening return.

This is materially different from the rejected ORB family. It does not use an
opening-range breakout, pullback, gap bias, VWAP, VIX, EMA, or trend filter.

## Fixed Mechanics

- Instrument: one MES contract.
- Signal window: 09:30-09:59 ET.
- Signal: sign of `09:59 close / 09:30 open - 1`.
- Entry: 15:30 ET bar open in the signal direction.
- Exit: protective stop or 15:59 ET bar close, whichever occurs first.
- Maximum one trade per day.
- No overnight position.
- Standard costs: $4 round-trip commission plus two ticks total slippage.
- Doubled costs: $8 commission plus four ticks total slippage.

## Development Grid

Only these values may be selected:

- Minimum absolute opening return: 0.00%, 0.05%, 0.10%, or 0.20%.
- Protective stop: 20 or 40 ticks (5 or 10 points; $25 or $50 before costs).

No additional filter or parameter may be added after viewing results from this
test.

## Chronological Design

- First 70% of sessions: development, split into three chronological regimes.
- Next 15%: selection and doubled-cost stress.
- Final 15%: family-level confirmation, not used to rank or filter candidates.

## Gates

Development candidate:

- At least 30 trades in each development regime.
- Positive expectancy in every development regime.
- Profit factor at least 1.05 in every development regime.

Selection survivor:

- At least 30 trades.
- Positive expectancy and profit factor at least 1.10.
- Positive doubled-cost expectancy and doubled-cost profit factor at least 1.05.

Final confirmation:

- At least 30 trades.
- Positive expectancy and profit factor at least 1.20.
- Positive doubled-cost expectancy and doubled-cost profit factor at least 1.10.
- Maximum drawdown no greater than $200 at standard costs.

## Decision Rule

Failure means reject this family as specified. Do not repair it by mining the
final period. Passing permits additional Monte Carlo and forward simulation,
not live or prop-firm execution.
