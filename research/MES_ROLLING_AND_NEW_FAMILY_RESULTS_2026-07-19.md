# MES Rolling Diagnosis and New-Family Results

Date: 2026-07-19
Execution state: research only; MES scheduled task disabled

## Data Repair

The continuous-contract normalizer now maps each `instrument_id` change to the
first actual subsequent RTH session. This correctly removes Monday/next-session
cross-contract gaps after Sunday or overnight rolls.

- Clean bars: 440,638.
- Clean sessions: 1,148.
- Roll-affected sessions excluded: 18.
- Materially incomplete sessions excluded: 0.
- Holiday sessions within tolerance: two sessions missing one minute each.
- Correct calendar: `CME Globex Equity`, including 13:15 ET futures half-days.
- Corrected CSV SHA256:
  `0A0840B9056F50523DC0360EADECB6D0499FCB75EF5E9FEEEBEA1306979BE9E6`

## Frozen ORB Rerun

The full 4,800-candidate executable search was rerun without changing any
parameters or gates.

- Development sessions: 803.
- Selection sessions: 172.
- Final sessions: 173.
- Development survivors: 5.
- Selection survivors: 1.

The same frozen 5-minute, 1-point breakout, 40-tick stop, 2R, gap-biased ORB
survived selection and failed final confirmation:

| Stage | Trades | P&L | Expectancy | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| Development | 46 | $516 | $11.22 | 1.37 | $294 |
| Selection | 11 | $156 | $14.18 | 1.48 | $120 |
| Selection, 2x costs | 11 | $112 | $10.18 | 1.32 | $140 |
| Final | 22 | $12 | $0.55 | 1.02 | $336 |
| Final, 2x costs | 22 | -$76 | -$3.45 | 0.91 | $372 |

Verdict: rejected.

## Rolling Diagnosis

The candidate was then evaluated unchanged in sequential, non-overlapping
126-session windows. This was diagnosis only, not optimization.

- Windows: 10, including one 14-session remainder.
- Profitable at standard costs: 5/10.
- Profitable at doubled costs: 4/10.
- Aggregate standard-cost P&L: $684.
- Aggregate doubled-cost P&L: $368.
- Worst window drawdown: $270 standard / $290 doubled.

Positive performance was clustered in early 2022 and 2024 through early 2025.
The setup lost or was effectively flat in 2023, late 2025, and 2026. Sparse
trade counts and regime concentration explain why aggregate development numbers
looked better than the final result.

Verdict: unstable and unsuitable for a $1,000 account or prop evaluation.

## Preregistered New Family: Close Momentum

Preregistration:
`research/MES_CLOSE_MOMENTUM_PREREGISTRATION_2026-07-19.md`

Hypothesis: the first 30-minute return predicts the final 30-minute return.
Eight configurations were fixed in advance using four opening-return thresholds
and two stop sizes. No ORB, gap, VWAP, VIX, EMA, or trend filters were used.

Result: zero development survivors. Every configuration had negative expectancy
in all three development regimes.

- Regime profit factors ranged approximately 0.41-0.80.
- Expectancy ranged approximately -$4.20 to -$11.40 per trade.
- Selection and final periods were not evaluated for momentum.

Verdict: rejected at development.

## Sequential Discovery Test: Close Reversal

Because momentum failed consistently, one fixed opposite-direction setup was
preregistered before touching its selection data:

`research/MES_CLOSE_REVERSAL_PREREGISTRATION_2026-07-19.md`

Frozen setup: fade an opening move of at least 0.10% during the final half hour,
40-tick stop, one MES contract.

Selection result:

- Trades: 113.
- P&L: -$474.50.
- Expectancy: -$4.20.
- Win rate: 40.71%.
- Profit factor: 0.83.
- Max drawdown: $736.50.
- Doubled-cost P&L: -$1,209.
- Doubled-cost expectancy: -$10.70.
- Doubled-cost profit factor: 0.63.
- Doubled-cost max drawdown: $1,295.50.

The selection gate failed, so the final 167 sessions were not evaluated for
this reversal hypothesis.

Verdict: rejected at selection.

## Profitability Decision

No MES strategy tested here has a deployable edge. More parameter variations on
the same sample would increase selection bias and could manufacture a profitable
backtest without improving future expectancy.

The correct action is:

1. Keep MES and Topstep execution disabled.
2. Do not buy a Combine from these results.
3. Continue the separate, safer `MicroMomentumPaper` equity lane and accumulate
   forward evidence there.
4. For future MES research, preregister a genuinely new mechanism and use either
   later forward-only data or richer order-flow data. Do not reuse the consumed
   ORB final period as a fresh holdout.
5. Require 30+ forward-simulation trades and all existing risk gates before any
   promotion review.

## Confidence

- Data integrity: 9/10.
- Test reproducibility: 9/10.
- Confidence the tested ORB is not ready: 9/10.
- Confidence close momentum/reversal is not ready: 9/10.
- Confidence any tested MES strategy can meet $100-$200/day on $1,000: 1/10.
- Confidence that continuing to mine this sample would be harmful: 9/10.

The work improved confidence by rejecting weak strategies before they could lose
real money. It did not produce a profitable futures system, and it should not be
described as one.
