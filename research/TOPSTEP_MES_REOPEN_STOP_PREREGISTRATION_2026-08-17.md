# Preregistration: MES Reopen Drift With Fixed Risk

Date: 2026-08-17
Status: frozen before inspecting intranight paths
Authority: research only; no order routing or sizing authority

## Reason For This Test

The preregistered reopen-drift baseline was positive in every annual split and
under two slippage stresses, but failed its fixed-one-contract maximum drawdown
gate. This test changes one item only: it adds a fixed protective stop selected
from the intended risk budget, not from an optimized parameter scan.

## Frozen Rule

- Reuse the entry, exit, contract-integrity, spread, fee, and split rules in
  `TOPSTEP_MES_REOPEN_DRIFT_PREREGISTRATION_2026-08-17.md`.
- Stop: 20.00 MES points below the executable entry ask, equivalent to $100 of
  price risk on one MES contract.
- Trigger: first same-contract BBO bid at or below the stop during the holding
  interval.
- Fill: the observed trigger bid, with no fill improvement.
- No profit target, trailing stop, time filter, event filter, or weekday filter.
- Stress 1 and Stress 2 retain the baseline's extra one- and two-tick-per-side
  deductions.

## Frozen Promotion Gate

The rule earns shadow-candidate status only when all conditions hold:

1. At least 100 trades in 2024 and 2025, and at least 75 in 2026.
2. Positive base expectancy in every annual split.
3. Positive full-sample expectancy under Stress 1.
4. Final-sample and full-sample base profit factors are at least 1.05.
5. Full-sample fixed-one-contract maximum drawdown is no worse than -$1,000.

Passing authorizes only a forward shadow recorder. Failure rejects the rule.
