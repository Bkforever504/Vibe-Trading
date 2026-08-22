# Options Shadow-Twin Confidence Preregistration

Date frozen: 2026-07-25

## Purpose

Measure whether the options bot's entry gates improve outcomes by following every
fully formed multi-leg credit candidate, including candidates blocked by the
shadow-consensus or execution gates. This is forward evidence only. It cannot
submit orders, change thresholds, promote a strategy, or overwrite history.

## Eligible population

- `put_spread` and `iron_condor` candidates that reached `_place_mleg`.
- Every leg must have a contract symbol, side, ratio, bid, and ask.
- Candidates missing executable quote sides are recorded and quarantined.
- Earlier scanner skips are outside this first trial because no complete contract
  structure exists for them.
- Duplicate contract sets from the same strategy and underlying within five
  minutes count once.

## Frozen prices and lifecycle

- Entry credit uses executable sides: sell legs at bid, buy legs at ask.
- Closing debit uses executable sides: buy short legs at ask, sell long legs at
  bid.
- Midpoint prices may be reported diagnostically but never grade P&L.
- Profit target: retain 50% of initial executable credit.
- Stop: closing debit reaches two times initial executable credit.
- Otherwise resolve at the first valid mark on expiration day at or after
  15:45 America/New_York.
- Quantity is the quantity that would have been submitted after any size-down.
- P&L is `(entry_credit - closing_debit) * 100 * quantity`.
- Fees are excluded until a broker-verified multi-leg fee series is available;
  all reports must disclose this limitation.
- Alpaca's indicative modified option feed is not OPRA NBBO. Execution fidelity
  is therefore capped below full confidence.
- Missing, crossed, stale, or incomplete quotes never become wins or losses.

## Decision groups

Each candidate receives one terminal decision label:

- `submitted`
- `blocked_shadow_consensus`
- `blocked_strict_caution`
- `blocked_execution_guard`
- `blocked_manual_approval`
- `submission_failed`

Blocked-versus-submitted comparisons are descriptive. They are not causal
estimates because the groups are selected by different rules.

## Frozen evidence gates

No strategy recommendation may be made before all of these are true:

1. At least 30 resolved candidates.
2. At least 20 distinct candidate dates.
3. At least 10 resolved blocked and 10 resolved submitted candidates for a
   blocked-versus-submitted comparison.
4. At least 80% of candidates have complete executable-side entry quotes.
5. At least 80% of scheduled marks have complete executable-side close quotes.
6. Positive conservative expectancy and profit factor above 1.0.
7. The lower Wilson bound for win rate is reported, not hidden.
8. Confidence calibration is measured with Brier score when at least 30
   predictions exist. A constant-base-rate benchmark must be shown.
9. Results survive double the configured transaction-cost stress once verified
   fee data exists.
10. A human reviews the immutable evidence before any production change.

## Earned-confidence contract

The shadow-twin score is a diagnostic from 0 to 10, composed of:

- data integrity: 0-2
- independent sample support: 0-2
- calibration: 0-2
- conservative expectancy robustness: 0-2
- execution fidelity: 0-2

Hard caps:

- fewer than 10 resolved candidates: maximum 3
- fewer than 30 resolved candidates or 20 dates: maximum 5
- negative conservative expectancy: maximum 3
- missing executable-side quote coverage below 80%: maximum 4
- no calibration advantage over a constant forecast: maximum 6
- indicative rather than OPRA NBBO quotes: maximum 8

A score of 10 would mean all stated evidence gates are satisfied. It would not
promise profit, a win rate, or a daily income.

## Trial boundaries

- First 30 resolved candidates are the frozen validation cohort.
- Any rule change starts a new version and a new cohort.
- The validation cohort is never retuned.
- Every candidate, mark, decision, and outcome is append-only JSONL.
- Failed captures remain visible as failed captures.
- Social-media claims and paid-indicator branding cannot override these gates.
