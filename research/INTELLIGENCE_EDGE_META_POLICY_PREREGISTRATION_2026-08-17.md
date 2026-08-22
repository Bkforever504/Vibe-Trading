# Intelligence Edge Meta-Policy Preregistration

Date frozen: 2026-08-17

## Hypothesis

A causal regime selector can improve one-MES expectancy after costs by using
trend-following setups only in directional regimes and mean-reversion setups
only in range regimes. The edge claim is the complete fixed policy, not any
individual indicator or an optimized parameter.

## Data And Evidence Status

- Instrument: MES, one contract, RTH one-minute bars.
- Historical source: local Databento continuous-contract export.
- Available period: 2022 through 2026-07-19.
- These dates have been consumed by earlier research. Results from this run are
  retrospective discovery evidence only and cannot authorize Practice trading.
- Any promotion requires new dates recorded after this specification.

## Frozen Candidate Families

- Trend: 15-minute opening-range VWAP breakout, first pullback with BOS
  confirmation, delta-fingerprint VWAP continuation.
- Range: false-breakout fade, VWAP-deviation fade.
- Opening-range configuration: 15 bars, 2.0 points minimum breakout, 1.5R
  target.
- First pullback: four-tick tolerance, eight-tick stop, BOS required.
- Delta threshold: 0.20.
- VWAP deviation: 4.0 points.
- Maximum one trade per session.

## Causal Intelligence Filter

At each candidate's entry bar, use only candles through that bar. A candidate
qualifies when all conditions hold:

1. regime compatibility is true;
2. data completeness is at least 0.65;
3. at least two independent supporting evidence families remain after
   correlated indicators are collapsed;
4. support ratio is at least 0.60;
5. conflict ratio is at most 0.35;
6. reward/risk is at least 1.0;
7. modeled friction is at most 35% of target reward.

Select the earliest qualifying candidate. Break same-minute ties by higher
intelligence score, then strategy name. No outcome may influence selection.

## Execution Model

- Baseline: one adverse tick on entry and exit plus $4.00 round-trip commission.
- Stress: two adverse ticks on entry and exit plus $4.00 commission.
- Stop wins same-bar ambiguity.
- Exit at target, stop, or final RTH close.
- No scaling, averaging, discretionary defense, or second trade.

## Chronological Reporting

- Development: through 2024-12-31.
- Confirmation: 2025-01-01 through 2025-12-31.
- Recent: 2026-01-01 onward.
- Report each segment independently plus the full sample.

## Review Gate

The historical candidate passes only if all conditions hold:

- at least 100 trades and 100 independent sessions;
- full-sample baseline profit factor at least 1.20;
- full-sample baseline and stress expectancy greater than zero;
- confirmation and recent expectancy both greater than zero;
- full-sample maximum drawdown no worse than -$500;
- expectancy remains positive after removing the best 5% of trades;
- 95% bootstrap lower bound for mean session PnL is greater than zero.

Even a pass means `forward_candidate`, never `practice_eligible`. A failure
freezes this exact policy as rejected; thresholds may not be tuned on these
same dates and presented as new evidence.
