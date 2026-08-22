# Evidence Confidence Upgrade Results

Date: 2026-07-25

## Honest baseline

- Elite options-stack readiness after adding the missing category: **5.7/10**.
- Risk controls: **10/10**.
- Learning loop: **8/10**.
- Counterfactual gate quality: **0/10**, correctly capped until forward
  candidates exist.
- Current score is an evidence status, not a profitability forecast.

## What changed

1. Added a preregistered, append-only options shadow twin for put spreads and
   iron condors.
2. Captures every fully formed candidate, including candidates blocked by
   consensus, caution, execution, or manual-approval gates.
3. Uses sell-at-bid and buy-at-ask entry credit; midpoint fills cannot grade
   results.
4. Uses buy-short-at-ask and sell-long-at-bid closing debit.
5. Tracks one frozen lifecycle: 50% credit profit target, 100% credit stop, or
   expiration hard close.
6. Reports Wilson win-rate uncertainty, profit factor, expectancy, quote
   coverage, calibration Brier score, and a constant-forecast benchmark.
7. Adds hard confidence caps for small samples, poor quote coverage, negative
   expectancy, failed calibration, and non-OPRA indicative quotes.
8. Feeds only robust negative outcomes into the self-learning mistake memory.
   Positive pre-fee outcomes remain withheld until verified fee truth exists.
9. Batches open-contract quote requests to avoid per-leg API pressure.
10. Registers `VibeTradingOptionsShadowTwin`, weekdays every 30 minutes from
    8:45 AM through 2:45 PM Central.

## Promotion gates

No parameter or production change is eligible until:

- 30 resolved candidates across 20 independent dates;
- at least 10 blocked and 10 submitted outcomes for descriptive comparison;
- at least 80% executable-side entry and mark quote coverage;
- positive conservative expectancy and profit factor above 1.0;
- Wilson uncertainty and confidence calibration are visible;
- cost stress passes after verified fee evidence is available;
- a human reviews the immutable cohort.

## What this learns

- Whether each warning cluster actually avoids losses.
- Whether strict caution blocks more losers than winners.
- Whether the internal 0-10 candidate grade is calibrated or decorative.
- Which strategy, underlying, regime, and decision groups retain expectancy
  under adverse-side pricing.
- Whether apparent edge survives execution friction and independent dates.

## Safety

- The tracker has no broker trading imports.
- It cannot submit, replace, cancel, or close an order.
- It uses read-only option snapshot GET requests.
- Telemetry errors never authorize an order or bypass an existing risk gate.
- Tests cannot write synthetic candidates into the production ledger.

## Verification

- 65 focused tests passed during the implementation pass.
- Production-path Python modules compile.
- Scheduled task is `Ready`; next run is Monday 2026-07-27 at 8:45 AM Central.
- The default shadow ledger is clean and contains no synthetic test records.
