# MES Opening-Gap Failure/Fade Preregistration - 2026-08-09

## Status

This is a research-only diagnostic. The full licensed history through
2026-07-19 has already influenced strategy development, so no slice of it is
independent confirmation. A favorable result can nominate one frozen shadow
configuration; it cannot enable execution or justify buying a Trading Combine.

## Hypothesis

After a material prior-close-to-open MES gap, an early move back toward the
prior close may identify a failed opening drive. Entering in the reversal
direction after that confirmation may have positive expectancy when the prior
close offers enough reward relative to the opening-window extreme stop.

This is narrower than the previously rejected generic opening-impulse reversal:

- the gap is measured from the previous completed RTH close;
- contract-roll boundaries and incomplete sessions are excluded;
- entry requires an explicit fraction of the gap to be rejected;
- the target is the prior close, not an arbitrary fixed multiple; and
- the trade is skipped when target/stop geometry is inadequate.

## Frozen Grid

- Start date: 2024-01-01.
- Minimum absolute opening gap: 0.35%, 0.50%, or 0.75%.
- Confirmation window: 5 or 15 completed one-minute bars.
- Minimum rejection toward the prior close: 25% or 50% of the gap.
- Stop: confirmation-window extreme plus 2 ticks.
- Target: previous completed RTH close.
- Minimum target/stop reward-risk: 1.25.
- Maximum initial risk: 60 MES ticks.
- Entry: next bar open after confirmation.
- Exit: target, stop, or 12:00 ET flatten; stop wins same-bar ambiguity.
- One trade maximum per session.

The 3 x 2 x 2 grid contains 12 attempts. Familywise one-sided alpha is
0.05 / 12. Results are also reported by calendar year; selection by aggregate
performance alone is prohibited.

## Costs And Stress

- MES point value: $5.00.
- Base per side: $1.24 commission/fees plus one tick slippage.
- Stress: 2x and 3x the complete round-trip cost.
- Additional checks: one-bar delayed entry at 2x costs and removal of the top
  1% of outcomes at 2x costs.

## Historical Stability Gate

A configuration is only a historical diagnostic survivor when:

- 2024 and 2025 each have at least 15 trades; partial 2026 has at least 8;
- every year is positive at base and 2x costs;
- every year's base profit factor is at least 1.05;
- aggregate 2x-cost profit factor is at least 1.10;
- aggregate 2x-cost expectancy remains positive with one-bar delay and without
  the top 1% of outcomes; and
- the familywise-adjusted one-sided mean test passes.

Even a survivor remains shadow-only. Promotion requires at least 60 resolved
post-2026-07-19 forward outcomes, three calendar months, positive 2x-cost
expectancy, profit factor at least 1.20, and acceptable 1-2 MES Combine risk.

## Research Basis

- Grant, Wolf, and Yu report index-futures opening reversals but explicitly
  warn that bid/ask transaction costs sharply reduce the effect:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=689282
- Cooper, Cliff, and Gulen document different overnight and intraday return
  behavior, including high opens that decline early:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1004081
- Lou, Polk, and Skouras study opposing overnight and intraday components:
  https://conference.nber.org/confer/2015/APf15/Lou_Polk_Skouras.pdf

These papers motivate a test; they do not establish that this implementation
is profitable in current MES data.
