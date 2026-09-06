# Trader Barbie 3-minute CE experiment — preregistration

Frozen before reading results on 2026-08-30. Shadow research only.

## New source detail

The supplied post says the execution is a **3-minute close through 50% CE**, the
second crossing is preferred after the first crossing fails, and positions are
not held longer than 30 minutes. This detail was not represented in the prior
5/10/15/30/60-minute tournament.

## Frozen lanes

All lanes use the existing causal 15-minute context: shifted 20-bar BSL/SSL,
sweep and close-back-inside, and the shifted 20-bar midpoint as CE.

1. `first_ce_cross`: enter after the first 3-minute close through CE.
2. `second_ce_recross`: ignore the first cross; require a close back through CE
   in the wrong direction followed by a second close through CE.
3. `second_ce_recross_strat2`: lane 2 plus a directional STRAT 2U for longs or
   2D for shorts on the second-cross candle.

The phrase “failed 2” is not fully defined by the post. Lane 3 is therefore an
explicit proxy, not a claim about the author's private rule.

## Execution and validation

- Source: genuine SPY 1-minute OHLCV, resampled causally to 15m and 3m.
- Only complete 390-minute RTH sessions are eligible.
- Entry: next 3-minute bar open. Stop: 15-minute sweep extreme. Target: 2R.
- Maximum hold: 10 completed 3-minute bars (30 minutes).
- Same-bar stop/target ambiguity: stop first.
- Friction: 4 bps round-trip on the underlying; doubled-friction stress is 8 bps.
- Confirmation window: 60 minutes after the completed 15-minute sweep.
- Three chronological folds; at least 50 trades, positive net expectancy,
  profit factor above 1.10, two positive folds, positive doubled-friction
  expectancy, and one-sided p-value below `0.05 / 992`.
- No QQQ 1-minute history is locally available. Therefore no result can satisfy
  cross-market confirmation or affect scanner ranks, A+/B+ alerts, sizing, or
  execution. A passing SPY lane may only be logged prospectively in shadow.

