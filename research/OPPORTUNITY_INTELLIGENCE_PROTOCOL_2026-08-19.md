# Opportunity Intelligence Protocol

Date frozen: 2026-08-19

## Objective

Measure whether the trading system is selecting the right opportunity, in the
right regime, at an executable price. The output is research evidence only. It
cannot submit orders, change a production gate, or promote a strategy.

## Daily lanes

The allocator evaluates five mutually comparable lanes:

1. QQQ mean reversion.
2. MES reopen-to-open drift.
3. Directional trend participation.
4. Defined-risk volatility premium.
5. Cash.

Every lane is written to the append-only opportunity ledger every day,
including rejected and unavailable lanes. Cash is an explicit allocation, not
a missing decision.

## Frozen diagnostics

1. **Regime allocation:** compatibility is determined from point-in-time source
   records. A lane with stale or incomplete context is unavailable.
2. **Gate attribution:** accepted and rejected candidates are retained so their
   later outcomes can be compared. A gate needs at least 10 resolved examples
   on each side before it receives a descriptive verdict.
3. **Placebo test:** historical net trade PnL is compared with 5,000 seeded
   random sign-flip paths. The one-sided p-value is the fraction whose mean is
   at least the observed mean. This tests a zero-location null; it does not
   prove causality.
4. **Edge decay:** the most recent 20 resolved observations are compared with
   the prior observations. Fewer than 30 total observations is insufficient.
   A non-positive recent mean or a recent mean below 50% of the prior mean is a
   watch; both conditions suspend research allocation.
5. **Portfolio simulation:** synchronized dated strategy PnLs are combined at
   uncertainty-adjusted weights, then evaluated with a moving-block bootstrap.
6. **Execution A/B:** midpoint, immediate executable, passive limit, and
   escalating limit policies are compared only when point-in-time quotes exist.
   Daily-bar proxies are labelled synthetic and cannot select an execution
   policy.
7. **Probability calibration:** probabilities must be frozen before outcomes.
   Historical diagnostics use an expanding Laplace-smoothed base rate.
8. **Uncertainty sizing:** a lane receives zero research weight when its
   bootstrap lower confidence bound is non-positive, evidence is insufficient,
   or decay is suspended. Eligible lanes are capped at 35% each; the remainder
   stays in cash.
9. **Operational SLO:** required sources must parse, source age is reported,
   and every output repeats `execution_enabled=false` and
   `can_submit_orders=false`.

## Evidence boundaries

- QQQ challenger evidence is development-only and failed experiment-wide
  multiple-testing correction. It remains shadow evidence.
- MES evidence is retrospectively corroborated and its independent bootstrap
  interval crosses zero. It remains shadow evidence.
- Options outcomes may omit fees when the source explicitly says so.
- Social posts, screenshots, rankings, and narrative sentiment cannot create a
  trade or increase a research weight.
- A positive report is not permission to paper, practice, or live trade.
  Promotion still requires the strategy's existing forward gate and explicit
  human approval.

## Change control

Any change to lane definitions, sample windows, placebo construction, decay
thresholds, allocation caps, or execution assumptions requires a new dated
protocol before evaluating the changed rule.
