# Preregistration: Topstep-Compliant MES Reopen Drift

Date: 2026-08-17
Status: frozen before simulation
Authority: research only; no order routing or sizing authority

Post-run audit correction: the initial implementation used the $0.70 MES
exchange fee instead of TopstepX's complete $1.22 round-turn cost. The code and
generated result were corrected to $1.22. This correction only makes the failed
promotion result more conservative; it was not used to alter the rule or gate.

## Hypothesis

The previously observed equity-index overnight premium remains positive after
the Topstep trading day reopens. A long MES position entered after the 5:00 PM
CT reopen and closed at the 8:30 AM CT cash open may retain enough of the
overnight premium to survive executable spread and fee assumptions.

## Frozen Rule

- Instrument: Databento continuous front-month MES BBO data.
- Entry: first valid ask from 6:00:05 PM through 6:00:30 PM ET.
- Exit: first valid bid from 9:30:00 AM through 9:30:10 AM ET on the next
  available cash session.
- Direction: long only, one MES contract.
- Contract integrity: entry and exit must have the same raw symbol. Rows that
  cross a roll or cannot be matched within four calendar days are excluded.
- Base friction: executable ask-to-bid prices plus the current $1.22 TopstepX
  MES round-turn cost.
- Stress 1: base result minus one MES tick per side ($2.50 round trip).
- Stress 2: base result minus two MES ticks per side ($5.00 round trip).
- No stop, target, regime filter, weekday filter, or event filter.

## Frozen Splits

- Development: exit dates in 2024.
- Selection: exit dates in 2025.
- Final: exit dates in 2026 through the last available observation.

## Promotion Gate

The rule earns **shadow-candidate** status only when all conditions hold:

1. At least 100 trades in development and selection, and at least 75 in final.
2. Positive base expectancy in every split.
3. Full-sample expectancy remains positive under Stress 1.
4. Final-sample base profit factor is at least 1.05.
5. Full-sample base profit factor is at least 1.05.
6. Full-sample fixed-one-contract maximum drawdown is no worse than -$1,000.

Failure of any condition rejects the rule. Passing permits a forward shadow
recorder only. It does not permit live or practice order submission.

## Diagnostics

Weekday cohorts and Stress 2 are reported after the frozen gate is evaluated.
They cannot rescue a failed baseline and cannot be promoted without a new
preregistration and untouched forward data.
