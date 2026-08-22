# Fibonacci Structure v1 Preregistration

Created before inspecting strategy outcomes.

## Hypothesis

A causally confirmed impulse followed by a 0.618-zone rejection has greater
out-of-sample expectancy than nearby non-Fibonacci pullback ratios.

## Fixed Rules

- Instrument: SPY, regular-session 5-minute bars.
- Swing anchors: unique 3-left/2-right confirmed pivots. A pivot cannot be used
  before the second bar after it.
- Minimum impulse: 1.25 trailing ATR(14).
- Candidate ratios: 0.382, 0.500, 0.550, 0.600, 0.618034, 0.650, 0.700.
- Zone: ratio plus or minus 0.025 of impulse size.
- Trigger: zone touch plus a completed directional rejection candle.
- Fill: next bar open.
- Stop: candidate ratio plus 0.168 of impulse, capped at 0.886.
- Target: prior impulse extreme.
- Maximum one trade per session per ratio.
- Same-bar stop/target ambiguity: stop first.
- Cost: 2 bps round trip; stress at 4 bps.
- Chronological split: 60% development, 20% selection, 20% untouched holdout.

## Promotion Gate

All conditions must pass on untouched holdout: at least 50 trades, positive
expectancy, profit factor at least 1.10, positive expectancy at double costs,
and expectancy above the median non-0.618 placebo ratio. Passing authorizes a
paper-only veto experiment, not live trading or autonomous size increases.
