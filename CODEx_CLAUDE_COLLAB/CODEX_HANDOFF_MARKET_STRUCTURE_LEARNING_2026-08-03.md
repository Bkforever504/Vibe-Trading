# Codex Handoff: Market-Structure Learning Upgrade

Date: 2026-08-03

## Objective

Turn existing candlestick, market-structure, higher-timeframe, catalyst, and execution observations into point-in-time shadow features that can be tested without lookahead. Keep all promotion and execution authority locked until the resulting cohorts survive robust forward-evidence gates.

## Implemented

- `scripts/candlestick_context_scanner.py`
  - Preserves timestamp indexes.
  - Computes current-session typical-price VWAP and prior-session high/low without future data.
  - Passes those levels into the existing VWAP reclaim, failed-breakout, and liquidity-sweep analysis.
- `strategies/flip_bot.py`
  - Advances shadow candidate schema to v4.
  - Freezes current, read-only candlestick, higher-timeframe, catalyst, and market-force reports at candidate creation.
  - Rejects stale or future-dated context rather than imputing it.
- `scripts/flip_shadow_time_bucket_report.py`
  - Adds setup-symbol and contextual market-structure cohorts.
  - Uses chronological 70/30 date holdout.
  - Reports executable quote coverage, doubled observed spread cost, top-5%-winner removal, drawdown, and profitable-day concentration.
  - Requires 100 outcomes, 20 dates, 30 holdout outcomes, 95% executable quote coverage, and positive full/holdout/stressed results before human review.
  - Remains read-only and cannot promote a setup or submit an order.
- `scripts/flip_feature_ablation_report.py`
  - Adds day type, market force, candlestick, higher-timeframe, and catalyst categories for later attribution.
- `scripts/elite_bot_readiness_scorecard.py`
  - Caps entry quality at 6 when mature market-structure cohorts exist but none passes every robustness gate.
  - A passing cohort adds only limited evidence and never changes execution authority.

## Current Evidence

- Primary Flip shadow lifecycles: 824 completed.
- Research-only lifecycles: 258 completed.
- Market-structure cohorts reviewed: 29.
- Cohorts passing the statistical review gate: 0.
- The 09:30 aggregate bucket has positive raw expectancy, but it is not live eligible and requires forward confirmation and human review.
- Post-hardening actual outcomes: 13 over 36 calendar days.
- Options twin: 2 resolved outcomes; conservative expectancy remains negative.
- Readiness: 6.6/10 overall.
- Operational integrity: 10/10.
- Risk controls: 10/10.
- Autonomous safety: 10/10.
- Entry quality: 6/10 due to no robust setup cohort.
- Execution remains disabled in all analytics reports. No orders were submitted by this work.

## Verification

- Core learning and safety suite: 122 passed.
- Wider options, calibration, verified-trader, Robinhood shadow, and failure-taxonomy suite: 176 passed, one third-party deprecation warning.
- Python compilation passed for all modified production modules.
- `git diff --check` passed; only expected CRLF conversion warnings were emitted.

## Next Work

1. Let schema-v4 shadow candidates accumulate point-in-time context so candle and higher-timeframe cohorts become measurable.
2. Improve executable quote coverage, especially historical spread telemetry, so doubled-cost stress can be computed instead of failing closed.
3. Diagnose setup-symbol cohorts that fail only one robustness condition; preregister any challenger before collecting new forward data.
4. Do not promote from social screenshots, raw PnL, aggregate win rate, or an in-sample candlestick pattern.
5. Keep live execution unchanged until a cohort passes every gate and receives explicit human review.

## Claude Review Request

Audit the implementation for point-in-time correctness, hidden lookahead, outcome duplication, cohort leakage, and cost-model optimism. Preserve fail-closed behavior and read-only authority. Do not relax sample floors or enable orders.

## Accelerated Historical Curriculum Addendum

- Added `research/market_scenario_curriculum.py` and preregistered the design before reading results.
- Processed 26,852 SPY/QQQ/IWM five-minute episodes from 2020-07-27 through 2026-07-17 in about 45 seconds.
- Five 504-session-train/126-session-test folds produced 680 trades at -2.7429 bps expectancy, 0.7978 profit factor, and zero profitable folds.
- Doubled-cost expectancy was -6.7429 bps; tripled-cost expectancy was -10.7429 bps.
- The untouched 252-session holdout produced 113 trades at -2.796 bps expectancy.
- Verdict: the v1 VWAP/EMA5-12/opening-range/range-regime policy is rejected and must not be tuned against the consumed holdout.
- Sparse, unseen, or cost-fragile scenarios map to abstain. The report remains underlying-directional research and cannot establish option profitability.
- The accelerated audit exposed a momentum parity defect: the canonical 5-trading-day forward tracker selected `XLE/IWM`, while the micro paper bot independently recomputed a weekly `XLE/XLK` ranking.
- `strategies/micro_momentum_paper_bot.py` now consumes the versioned canonical state from `data/edge_forward_state.json`, rejects stale or mismatched strategy versions, and keys idempotence to the canonical rebalance date rather than calendar week.
- No broker-order method was added or enabled. The micro ledger remains local virtual paper only.

## Historical Options NBBO Curriculum Addendum

- Preregistered and implemented `research/options_nbbo_curriculum.py`.
- Supports JSON, JSONL, and parquet candidate-scoped quote extracts for call
  spreads, put spreads, and iron condors.
- Requires concrete, point-in-time OCC contracts and rejects future selection,
  expired contracts, missing maximum risk, or incomplete target/stop policy.
- Entry is short legs at bid and long legs at ask. Exit is short legs at ask
  and long legs at bid. Midpoint fills, underlying-return substitution, option
  bar spread proxies, and missing-leg imputation are prohibited.
- Rejects non-NBBO scopes, crossed/zero markets, quotes older than two seconds,
  inter-leg skew above two seconds, and relative spreads above 25% of mid.
- Applies $0.66 per contract, per leg, per side and reports base, double-fee,
  and triple-fee results.
- Separates the final 20% of candidate dates as a locked holdout and requires
  30 resolved candidates, 80% lifecycle coverage, three chronological blocks,
  60% profitable blocks, robust development expectancy, and 10 positive
  holdout outcomes before human review.
- Added `data/options_nbbo_curriculum_results.json` to the elite readiness
  scorecard. Missing or failed historical executable-quote evidence caps
  counterfactual gate quality at 4 or lower.

### Actual Local Coverage Result

- Candidate count: 2.
- Quote observations: 136.
- Quote scope: all 136 are
  `alpaca_indicative_modified_not_opra_nbbo`.
- Eligible historical NBBO lifecycles: 0.
- Status: `coverage_unavailable`; review gate failed.
- This is a data-coverage result, not a negative option-strategy trial. Do not
  record it as edge failure and do not substitute option bars or midpoints.
- Current readiness after wiring the result: 6.9 overall; counterfactual gate
  quality 3.0 due to the existing two losing resolved shadows plus missing
  historical NBBO evidence.

### Claude Review Request

Audit `research/options_nbbo_curriculum.py` for quote-time lookahead, OCC expiry
handling, asynchronous-leg synchronization, fee multiplication, target/stop
ordering, locked-holdout isolation, and large-tape performance. Preserve all
fail-closed behavior. The next legitimate input is a licensed, candidate-scoped
OPRA NBBO extract; do not relax the scope check or enable execution.

### Verification

- New NBBO and readiness tests: 34 passed.
- Expanded options and readiness suite: 72 passed, one third-party warning.
- Full repository suite: 4,398 passed, 4 skipped, 4 existing deprecation
  warnings in 225.26 seconds.
- Python compilation and scoped `git diff --check` passed.
- `uv run python -m pytest -q` remains blocked before collection by invalid
  upstream `zigzag==0.3.2` package metadata; the provisioned repository Python
  environment completed the full suite successfully.
- No orders were submitted and no execution setting was enabled.

## Licensed OPRA Acquisition And Cadence Update

This section supersedes the indicative-only coverage result above but does not
supersede its safety conclusions.

- Added `scripts/fetch_databento_options_nbbo.py` and
  `scripts/run_databento_options_nbbo_curriculum.ps1`.
- The downloader is estimate-only by default, requests exact frozen OCC
  contracts only, caps the request to provider availability, aborts above a
  hard cost ceiling, fingerprints the request, and writes immutable DBN plus
  normalized provenance artifacts.
- Downloaded Databento `OPRA.PILLAR` `cbbo-1s` for four exact SPY/QQQ
  contracts. Estimated and confirmed cost: $0.031057. Input rows: 208,248;
  invalid market rows excluded: 251; eligible normalized CBBO rows: 207,997.
- Immutable DBN SHA-256:
  `fb1a7531cd226751934280f37f419d0543bc7d3aec6e9b3e7e82749b482b92de`.
- Normalized JSONL SHA-256:
  `bd301b45e10f8fd52a16f5021ab070ffb190eb2f56721ca6ebb293573d7efae3`.
- Both blocked call-spread candidates reached their executable 50% target in
  the historical CBBO replay. Base-fee counterfactual PnL was $190.08 for SPY
  and $116.72 for QQQ.
- Review remains failed: only 2 resolved candidates from 1 date, versus the
  frozen 30-resolved, 3-block, and 10-holdout minimums. No parameter, sizing,
  or promotion authority changed.
- The forward indicative twin later marked both candidates as losses. The
  discrepancy is now explicitly treated as quote-source and sampling risk,
  not proof that either outcome source is a broker fill.
- A post-result cadence diagnostic found one-minute scheduled OPRA observation
  saw both target windows, while five- and thirty-minute schedules saw one.
  This diagnostic cannot count as strategy evidence.
- `VibeTradingOptionsShadowTwin` now repeats every minute from 08:45 through
  14:55 Central. It remains read-only with no order endpoints.
- `IWM-Bot-Monitor` now repeats every minute from 08:35 through 15:00 Central,
  and its task runner explicitly pins `ALPACA_PAPER=true`.
- Task Scheduler repetition is encoded through the supported weekly-trigger
  XML because the PowerShell trigger cmdlet does not expose that combination.
  `market_schedule_alignment.py` now audits interval and duration, not only
  start time.
- Both tasks completed an immediate verification run with exit code 0.
  Schedule governance passed 56/56 tasks with zero issues and one pre-existing
  extra-trigger warning for `Flip-Bot-Monitor`.

### Additional Verification

- Downloader, curriculum, and schedule tests: 30 passed.
- Full repository suite after the acquisition and cadence changes: 4,409
  passed, 4 skipped, 4 existing deprecation warnings in 212.19 seconds.
- No live orders were enabled or submitted. The IWM monitor can act only on
  Alpaca paper positions under its scheduled runner.

### Claude Review Request

Audit the Databento request/cost guard, raw-symbol normalization, sampled-CBBO
time semantics, polling replay, weekly-trigger XML mutation, and paper-mode
pin. Specifically challenge whether one-minute polling adds API or scheduler
failure risk and whether a broker-held paper profit order can be implemented
without an MLEG cancel/fill race. Do not add that order until cancellation,
partial-fill, restart-recovery, and stop-race tests exist.

## Paper Resting Target And Incremental Evidence Update

- Added an opt-in broker-held DAY profit target for confirmed Alpaca paper
  MLEG fills. The scheduled monitor pins both `ALPACA_PAPER=true` and
  `ENABLE_PAPER_RESTING_PROFIT_ORDERS=true` before module import.
- The target debit uses the trade's broker-confirmed entry credit and frozen
  `profit_close_pct`. Close legs must exactly match the tracked OCC set and
  reverse every recorded entry side with explicit close position intents.
- Deterministic client order IDs plus Alpaca client-ID lookup recover a target
  whose submission response was lost. Existing IDs make restart submission
  idempotent.
- Full fills close state only after exact MLEG leg-set, quantity, and fill
  economics verification. Partial fills and unknown statuses require manual
  reconciliation and fail closed.
- Before stops, defensive exits, near-target exits, or IC rolls, the target is
  canceled and then re-read. A second exit is forbidden until the target is
  terminal and unfilled. A target that fills during cancellation becomes the
  sole verified close.
- Exact target observations leave the broker-held order active instead of
  canceling it and chasing a second exit.
- Alpaca options support DAY rather than GTC orders, so terminal targets are
  retired and a new per-session attempt can be established on the next
  monitor cycle.
- Forward quote scope is now derived from the configured Alpaca feed rather
  than hardcoded. The production shadow runner explicitly remains on
  `indicative`; those marks are diagnostic, not OPRA promotion evidence.
- A read-only Alpaca OPRA probe returned HTTP 403 with `OPRA agreement is not
  signed`. No subscription or agreement change was attempted.
- Added an incremental unresolved-candidate Databento lane. It resumes with a
  two-second overlap, deterministically merges normalized rows, and no-ops
  without a provider request when all candidates are resolved.
- Registered `VibeTradingNightlyOptionsNBBOEvidence` for 20:15 Central on
  weekdays with a hard $0.05 per-run ceiling. Its verification run no-op'd,
  spent $0, and returned 0 because both existing candidates are resolved.
- Schedule governance now passes 57/57 tasks with zero issues and the existing
  `Flip-Bot-Monitor` extra-trigger warning.
- The paper monitor verification run returned 0, found no open option
  positions, and submitted no order. The first actual paper target lifecycle
  remains required operational evidence.

### Verification

- Focused options, quote, downloader, and schedule suite: 119 passed.
- Full repository suite: 4,423 passed, 4 skipped, 4 existing dependency
  deprecation warnings in 214.86 seconds.
- Final order-refresh, target-state, downloader, quote, and schedule subset
  after explicitly requesting nested MLEG legs: 109 passed.
- Python and PowerShell syntax validation passed.

### Claude Review Request

Audit `strategies/iwm_options_bot.py` for target-order sign, credit/debit
semantics, partial strategy fills, stale broker snapshots, cancel/fill races,
DAY expiration, client-ID recovery, roll interaction, and state-save ordering.
Audit the incremental downloader for missed new candidates, per-symbol
coverage gaps, deduplication leakage, repeated billing, and cost-guard bypass.
Keep the feature paper-only and do not weaken any promotion gate.
