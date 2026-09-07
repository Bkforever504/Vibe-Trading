# Repo Eval: Hypothesis

**Date:** 2026-09-07
**Repo:** https://github.com/HypothesisWorks/hypothesis
**License:** MPL 2.0
**Stars:** 7.5k+
**Language:** Python 3.8+

## Idea
Add property-based tests for math-heavy paths: sizing calculations, exit ratchets, stop-loss logic, VWAP/EMA computations, expected-move math, IVR normalization, ratchet triggers. Auto-generates edge-case inputs the example-based test suite misses.

## Source
Direct evaluation. Motivated by:
- 11 test failures on baseline recovery (obs S484)
- Exit ratchet, profit-protect, sizing math complexity (per `vibe-trading-exit-logic` skill)
- Zero property-based tests in current suite (repo inspection: only pytest example tests)
- Whole classes of edge cases untested: extreme IVR, near-zero volume, gap opens, holiday sessions, DST transitions, negative fills

## Edge (Error Reduction)
Hypothesis provides:
- **@given decorators** with strategies (integers, floats, dataframes, dates)
- **Shrinking** — when a test fails, Hypothesis auto-reduces to the minimal failing input
- **Statistical guarantees** — hundreds of inputs per test run, catches boundary bugs example tests never touch
- **Pandera integration** — auto-generates DataFrames matching declared schemas
- **Stateful testing** — for order state machines (open → filled → managed → closed)
- **Regression database** — remembers past failures, re-tests them on every run

## Data Needed
None. Test-only.

## Implementation
**Simple.** Add to `tests/` alongside existing pytest tests.

Phase 1 (1 day): property tests for `strategies/flip_bot.py` sizing + exit math.

Phase 2 (2-3 days): property tests for IWM options bot spread math, credit/debit calc, greeks-based sizing.

Phase 3 (ongoing): stateful test for order lifecycle (open → partial fill → managed → close), guard threshold invariants.

## Fit With Current Stack
- Pure Python, pip-install, no infra
- Runs inside existing pytest suite
- Complements pandera (auto-generates schema-conforming DataFrames)
- Zero effect on live trading — test-only
- Deterministic failure reproduction via regression database

## Ratings (1-5)
- Edge clarity: **4** — catches unknown-unknowns, hard to prove ROI until first bug caught
- Implementation complexity: **1** — drop-in
- Data availability: **5** — no new data
- Fit with stack: **5** — pure additive

## Verdict
**intake_shadow** → Adopt alongside Prefect + Pandera.

## Reason
Cheap to add. Highly effective at finding boundary bugs in math paths. Vibe-Trading has many math paths.

## Handoff
See `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-09-07_ERROR_REDUCTION_STACK.md` for implementation plan.
