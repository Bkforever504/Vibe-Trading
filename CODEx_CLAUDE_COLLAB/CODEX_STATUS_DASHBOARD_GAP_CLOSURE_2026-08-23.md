# Dashboard Gap Closure Status — 2026-08-23

## Outcome

The dashboard evidence path is implemented end to end for read-only, manual-decision support:

`completed bars -> canonical pattern grade -> immutable plan -> append-only detection -> outcome resolution -> calibration -> daily A+ reconciliation -> dashboard gate`

The system remains fail-closed. It does not convert an A/A+ grade into a probability claim or order permission.

## Closed gaps

- Added a canonical pattern-grader scanner with stable detection/lifecycle IDs, immutable plan hashes, completed-bar provenance, feed-quality fields, and a reconciled scan denominator.
- Added weekday scanner and aggregation tasks. The intraday task runs every five minutes during its configured window; the runner skips weekends.
- Connected the pattern ledger and producer-health report to the daily A+ review inventory.
- Added a visible Daily Review Gate to the main Trading Cockpit. It exposes missing/failed producers, source coverage, reviewed setups, and outcome follow-ups before the command card.
- Replaced the hard-coded 100% daily review result with source and enumerated-setup reconciliation.
- Added nested setup discovery so A/A+ setups inside market-structure watchlist rows are reviewed.
- Added source-specific freshness SLAs and future-clock-skew quarantine. Stale live candidates are demoted to research-only and lose probability-ranking eligibility.
- Added periodic higher-timeframe refresh and stale-required-timeframe blocking.
- Made candidate plan IDs stable across display dates.
- Connected pattern outcomes to the calibration service, with latest-snapshot deduplication.
- Corrected historical bar retrieval, entry-touch requirements, unfilled outcomes, conservative stop/target ordering, and MFE/MAE-in-R output.
- Corrected detection event identity and coverage-delta units.
- Bound the direct dashboard backend to `127.0.0.1`; the authenticated gateway remains the remote boundary.
- Preserved `execution_enabled=false` and `can_submit_orders=false` throughout every new surface.

## Live truth at handoff

- Cockpit schema: `10`
- Mode: `read_only_decision_support`
- Daily Review Gate: `attention_required`
- Overall/source review coverage: `94.1%` (`16/17` declared sources reviewed)
- Failed producer: `pattern_grader_status`
- Canonical pattern detections in the current report: `0`
- Pattern producer failures in the current report: `1`
- Qualified calibration outcomes: `0`
- Direct backend listener: `127.0.0.1:8899`
- Authenticated gateway listener: `127.0.0.1:8898`

The amber state is correct on Sunday: the available live-opportunity report is a stale legacy fallback without the canonical `pattern_grade_v1` watchlist. The scanner refuses to manufacture grades from it. The weekday producer and scanner schedules must create and verify the first canonical live observations.

## Remaining evidence gates

1. **Independent MOVE denominator:** `move_universe_ground_truth.py` still contains a legacy radar-derived proxy. It is explicitly marked unqualified and cannot contribute precision/recall. The frozen MOVE spec requires a causal ATR/retention/R-multiple builder over the declared symbol×timeframe matrix.
2. **Pattern-family truth contract:** the frozen MOVE spec labels price displacements but does not independently label which pattern family existed. Aggregate opportunity recall can be measured from price moves; per-family recall needs an independent annotation/detector contract before it is ground truth.
3. **First weekday production proof:** verify that the live opportunity engine emits `pattern_grade_v1`, the scanner reconciles its denominator, and the daily gate clears the producer failure.
4. **Calibration evidence:** collect at least 100 resolved outcomes across at least 30 independent dates, with positive Brier skill versus the expanding base rate, before showing probability-led ranking.
5. **Execution-quality truth:** capture manual intended entry, actual fill, partial/unfilled state, slippage, fees, and exit fill so net-after-cost outcomes can replace OHLC-touch simulations where available.
6. **Options-feed qualification:** keep dealer/GEX/0DTE context informational unless the underlying quote/OPRA entitlement and freshness fields are independently qualified.

None of these gates should be bypassed to make the dashboard look greener.

## Verification

- Full backend suite: `5121 passed, 4 skipped`
- Focused dashboard/backend suite: `135 passed`
- Safety/authority/secret suite: `10 passed`
- Frontend suite: `217 passed`
- Frontend production build: passed
- Execution gate audit: passed, `0` issues
- Order-authority invariant: `0` violations
- Secret leak guard on touched files: `0` findings
- Python compilation: passed
- `git diff --check`: passed
- No order submitted; no live-bot body, broker credential, or signal-registry edit made

## Research basis

The primary-source research and implementation priorities are recorded in `research/DASHBOARD_GAP_RESEARCH_PRIMARY_SOURCES_2026-08-23.md`.

## Worktree

Changes remain uncommitted for review. Pre-existing edits to `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_LOOP_CLOSURE_2026-07-07.md`, the `tools/tradingview-mcp` submodule state, and `output/` were preserved and not folded into this work.
