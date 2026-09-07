# Repo Eval: Pandera

**Date:** 2026-09-07
**Repo:** https://github.com/unionai-oss/pandera
**License:** MIT
**Stars:** 3.5k+
**Language:** Python 3.9+

## Idea
Add DataFrame schema validation at scanner and strategy module boundaries. Catches column drift, dtype flips, NaN leakage, out-of-range values before they poison signals or orders.

## Source
Direct evaluation. Motivated by:
- 293 dirty hygiene entries (obs S484)
- Strategy staleness alerts (obs 3085)
- No standardized schema contract between scanners and strategies (repo inspection)
- Silent-failure class of bugs where a scanner returns DataFrame with renamed/missing column and downstream logic falls through to "no signal"

## Edge (Error Reduction)
Pandera provides:
- **Schema decorators** on function inputs/outputs — validation runs automatically
- **DataFrameModel classes** — Pydantic-style declarations for column names, dtypes, nullability, value ranges, uniqueness
- **Lazy validation** — collects all errors instead of failing on first (better debugging)
- **Hypothesis integration** — auto-generates DataFrames matching schema for property tests
- **pandas + polars support** — future-proof if perf migration happens
- **Fast validation** — checks are vectorized, minimal runtime cost

## Data Needed
None. Wraps existing DataFrame flows.

## Implementation
**Simple.** Drop-in decorators. No architectural change.

Phase 1 (1 day): schema classes for shared feature fabric outputs (OHLCV, IVR, HMM state, breadth, VWAP).

Phase 2 (2-3 days): schemas on top 10 scanner outputs (pattern_grader, gex_scanner, hmm_regime_scanner, ivr_scanner, momentum_edge_ensemble_shadow, etc.).

Phase 3 (ongoing): schemas on strategy inputs (flip_bot, iwm_options_bot). Any scanner emitting bad frames fails-loud instead of silently no-signaling.

## Fit With Current Stack
- Pure Python, pip-install, no infra
- Complements existing `tests/` — schema doubles as documentation
- Works with existing pandas usage (repo is pandas-heavy)
- Integrates with hypothesis (see repo_eval_hypothesis)
- Zero effect on live trading — validation-only, no data transformation

## Ratings (1-5)
- Edge clarity: **5** — kills a documented silent-failure class
- Implementation complexity: **1** — drop-in decorators
- Data availability: **5** — no new data
- Fit with stack: **5** — pure additive

## Verdict
**intake_shadow** → Adopt immediately alongside Prefect. Non-competing scope.

## Reason
Highest ROI-per-line-of-code addition. Catches a class of bugs the test suite currently cannot express.

## Handoff
See `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-09-07_ERROR_REDUCTION_STACK.md` for implementation plan.
