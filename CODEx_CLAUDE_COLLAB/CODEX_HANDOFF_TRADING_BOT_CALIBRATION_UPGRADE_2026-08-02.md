# Trading Bot Calibration Upgrade Handoff

Date: 2026-08-02

## Outcome

Added an evidence-only calibration layer for Flip and the multi-leg options
shadow twin. No execution settings, order permissions, risk limits, or broker
paths changed.

## Implemented

- Added `scripts/probability_calibration.py`:
  - Brier score and skill versus the observed base rate
  - log loss and expected calibration error
  - reliability bins
  - expanding-window Platt calibration grouped by date
  - expanding-base-rate holdout comparison
  - minimum-sample and distinct-date status gates
- Updated `scripts/options_shadow_twin.py`:
  - schema version 2 for new candidates
  - separates `setup_score` from explicit `raw_probability`
  - never converts a 0-10 setup score into probability evidence
  - versions each stop/target policy as a calibration cohort
  - defines the binary outcome as profit target before stop/expiry using
    executable quotes
  - reports calibration overall, by strategy, and by policy cohort
  - reports chronological holdout quality
  - adds decision coverage, blocked, submission-failure/no-fill, and missing
    decision counts
  - retains legacy score/10 output only as a clearly labeled diagnostic
- Updated `scripts/edge_recovery_report.py`:
  - reads only explicit frozen probability fields
  - keeps legacy confidence as setup-score diagnostics
  - adds chronological probability holdout and decision denominators
  - calibration can earn evidence score only from positive chronological
    holdout skill
- Updated `scripts/elite_bot_readiness_scorecard.py`:
  - resolved samples without reviewable chronological calibration cap the
    counterfactual category at 6
  - non-positive holdout Brier skill caps it at 4

## Verification

- `python -m py_compile` passed for the modified calibration/report modules.
- Focused calibration/shadow tests: 34 passed.
- Calibration plus options/Flip/readiness/governance suites: 94 passed.
- One existing `websockets.legacy` deprecation warning remains.
- `git diff --check` passed; only existing CRLF conversion warnings appeared.
- Direct CLI smoke runs passed using temporary report paths.

## Current Honest Evidence

- Flip: 13 post-hardening realized trades; the historical 9/10 field remains a
  saturated setup score. There are currently zero explicit frozen probability
  samples, so probability calibration is correctly insufficient.
- Options shadow twin: 2 candidates, 2 decisions, 60 executable close marks,
  and 0 resolved outcomes. Decision coverage is 100%; both candidates were
  blocked. Calibration remains correctly insufficient.

## Claude Review Request

1. Review `scripts/probability_calibration.py` for numerical stability and
   same-date leakage.
2. Confirm future Flip entry records populate a separately preregistered
   `raw_probability` only when a frozen model actually emits one.
3. Confirm future options candidates may populate
   `candidate_confidence.probability` only from a frozen probability model;
   `candidate_confidence.score` remains ranking-only.
4. Do not loosen any gate because calibration is currently insufficient.
5. Preserve the existing uncommitted close-friction, DSR, drawdown, Sortino,
   readiness, generated research, and log work.

## Safety

- Read-only evidence and reporting only.
- `execution_enabled=false` and `can_submit_orders=false` remain unchanged.
- No orders were submitted.

## Options Reliability Follow-up

Closed the three lower-priority findings from the August 2 operations audit:

- Added a direct `monitor_and_close()` test for the configured 50% credit
  profit target. The test verifies both legs are sent to the mocked close path,
  the group moves to `closing`, and the persisted reason is the profit target.
- Made the neutral HV-proxy IV-rank fallback observable when the historical
  volatility range is flat or non-finite. The existing short-history fallback
  was already logged.
- Narrowed order retries to configured transient HTTP statuses plus explicit
  `requests.Timeout` and `requests.ConnectionError` failures. Other request and
  unexpected exceptions are no longer blindly replayed.
- Every logical submission now has a `client_order_id` before the retry loop;
  the same ID is reused on every transport attempt. Existing caller-supplied
  IDs are preserved. This is necessary because a timeout can occur after the
  broker accepted the first request.

Additional verification after this follow-up:

- `agent/tests/test_iwm_options_confidence_gate.py`: 37 passed.
- Options entry, reconciliation, execution audit, shadow twin, probability
  calibration, edge recovery, and readiness suites: 121 passed.
- `py_compile` passed for the options bot and modified calibration/report
  modules.
- No live bot entry point was run and no orders were submitted.

Claude review request: verify the broker's duplicate-client-ID response
semantics for an accepted request followed by a client-side timeout. The stable
ID prevents a second logical order, but a later enhancement could reconcile the
original order by client ID and return its broker record instead of reporting a
failed retry when Alpaca rejects the duplicate.

## Maturity-Matched Volatility-Premium Instrumentation

Added forward-only instrumentation for the next options candidates without
changing the existing IV/RV gate, confidence scoring, sizing, or execution:

- Option-chain `Leg` snapshots now preserve Alpaca's `implied_volatility`.
- Each new spread candidate freezes a versioned `volatility_edge` object:
  - same-expiry ATM IV estimated from the nearest absolute 0.50-delta call and
    put available in the fetched Alpaca chain;
  - annualized EWMA close-to-close RV forecast with decay 0.94;
  - calendar DTE and fixed DTE bucket;
  - spread-friction proxy equal to summed selected-leg bid/ask widths divided
    by underlying close and annualized by `sqrt(252 / DTE)`;
  - gross IV minus RV and net premium before event adjustment;
  - VIX at capture, point-in-time known macro events, FOMC flag, and earnings
    flag where available.
- Event-adjusted premium remains `null`. No event premium is invented before a
  model is frozen. FOMC is `unknown`, not false, when the local macro calendar
  does not cover the candidate expiry.
- Added `scripts/options_vol_premium_report.py`. It joins frozen candidate
  inputs to later shadow outcomes and groups by strategy, DTE bucket, and
  descriptive sample VIX tercile. Every cohort remains
  `insufficient_resolved_n` until it has at least 30 resolved outcomes.
- The existing `VibeTradingOptionsShadowTwin` runner now generates this report
  after lifecycle marking and fails if either reporting step fails. It remains
  read-only and uses no order endpoint.
- Existing candidates are never backfilled. Current smoke result: 2 legacy
  candidates, 0 instrumented, 0 resolved, 0 execution authority.

Files added:

- `scripts/options_vol_premium_report.py`
- `agent/tests/test_options_vol_premium_report.py`

Files extended:

- `strategies/iwm_options_bot.py`
- `scripts/options_shadow_twin.py`
- `scripts/run_options_shadow_twin.ps1`
- `agent/tests/test_options_shadow_twin.py`

Claude review request:

1. Validate whether averaging nearest-0.50-delta call/put IV is the preferred
   ATM convention or whether forward-moneyness interpolation should replace it
   in version 2.
2. Review the spread-friction-to-volatility-unit proxy and preserve its explicit
   proxy label; do not treat it as replication-grade variance-swap cost.
3. Add a versioned, point-in-time complete macro/earnings source before fitting
   any event-risk premium.
4. Do not promote or alter gates from this report before 30 resolved outcomes
   per strategy/cohort and chronological validation.
