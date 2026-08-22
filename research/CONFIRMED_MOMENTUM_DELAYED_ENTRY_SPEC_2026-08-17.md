# Confirmed Momentum Delayed-Entry Specification

Date frozen: 2026-08-17

## Hypothesis

The previously observed first-mark momentum split is useful only if it remains
profitable after waiting for confirmation. A causal policy therefore enters a
directional option candidate at the first post-signal mark's recorded ask only
when that mark is positive, then evaluates every exit at recorded bids.

## Evidence Status

- The existing shadow corpus was inspected before this specification and is
  consumed discovery history.
- Rows dated after 2026-08-17 are prospective forward evidence.
- Historical success can nominate this policy for forward observation only.
- This policy has no paper or live execution authority.

## Frozen Entry

1. Require a complete lifecycle with a `shadow_entry`, at least one
   `shadow_mark`, and a `shadow_exit`.
2. The first mark must arrive from 0 through less than 10 minutes after the
   signal.
3. Its midpoint return from the original signal price must be strictly greater
   than zero.
4. Enter at that first mark's recorded ask. Missing or non-positive asks make
   the lifecycle ineligible; no midpoint fallback is allowed.

## Frozen Exit

Evaluate only later recorded bids relative to the delayed entry ask:

- stop at -30%;
- target at +75%;
- arm profit protection at +25%;
- protected floor is the greater of +15% and best return minus 10 points;
- at best return of at least +30%, floor is at least +20%;
- at best return of at least +40%, floor is at least +30%;
- otherwise exit at the recorded lifecycle exit bid.

The first qualifying observation wins. No target, stop, or threshold may be
changed after reading the result.

## Costs And Review Gate

- Executable spread cost is embedded by buying at ask and selling at bid.
- Baseline subtracts another 1.5 percentage points per trade.
- Stress subtracts 3.0 percentage points per trade.
- Require at least 100 trades and 30 independent dates.
- Require profit factor at least 1.20.
- Require positive baseline, stress, top-5%-winner-removed, and chronological
  last-20%-of-dates expectancy.
- Require a date-cluster bootstrap 95% lower mean above zero.

Consumed-history and forward evidence are reported separately. Only the
forward partition may eventually request human paper review. It cannot enable
execution automatically.
