# Claude Code Handoff: ORB Retest and Premium-Level Research

Date: 2026-07-16

## User Decision

The user approved the first-five-minute ORB breakout/retest pattern for the Flip bot execution path and approved two research additions:

1. Breakout-candle dislocation velocity and close-location telemetry.
2. Same-day option premium concentration levels from executed option trade prints.

This change does **not** turn on real-money brokerage execution. Existing paper/live environment settings were not changed.

## Implemented Behavior

### ORB breakout/retest execution candidate

`strategies/flip_bot.py` now requires ORB-originated 0DTE execution candidates to satisfy all of the following:

- Build the opening range from the first five completed one-minute bars.
- Observe a later completed candle close outside that range.
- Observe a subsequent completed candle touch the broken boundary within a range-scaled tolerance.
- Require that retest candle to close back outside the opening range.
- Reject a deep close back inside the range as invalidation.
- Require the confirmed retest to remain fresh: no more than 15 one-minute bars old.
- Require the latest completed price to remain outside the range.
- Stop considering the setup after the first 60 minutes.

The execution candidate records breakout/retest timestamps, status, age, tolerance, ATR ratio, close-location value, and dislocation z-score.

Gap, calendar-catalyst, trend, risk, liquidity, reconciliation, authorization, kill-switch, sizing, stop, target, and ratchet behavior were not loosened.

The accelerated shadow logger deliberately calls the same finder with `require_orb_retest=False`. This preserves raw-breakout counterfactuals so future reports can compare raw ORB versus confirmed retest without weakening execution.

### Dislocation and close-location telemetry

The breakout candle now records:

- True-range dislocation relative to its prior EWMA-conditioned distribution.
- Dislocation z-score when enough prior bars and nonzero dispersion exist.
- Raw close-location value.
- Direction-adjusted close-location value.
- Explicit unavailable/insufficient-history status rather than synthetic values.

These fields are **telemetry only**. They do not block trades, alter direction, or change size.

### Option premium-level logger

New read-only module: `scripts/option_premium_level_logger.py`.

- Discovers near-money same-day option contracts.
- Fetches historical option trade prints one contract at a time to prevent symbol-first pagination from starving one option side.
- Aggregates executed premium as `option_price * contract_size * 100`, grouped by strike and call/put right.
- Records top levels, trade counts, contracts traded, VWAP option price, timestamps, condition codes, completeness, and feed provenance.
- Does not infer buyer/seller aggressor without contemporaneous quote classification.
- Has no order imports or submission path.
- Writes the current report to `%USERPROFILE%/.vibe-trading/reports/option-premium-levels.json` and appends research history to `data/option_premium_level_log.jsonl`.

The Flip entry snapshot reads a same-day report and records nearest/top call and put levels. It never gates an entry.

The scheduled task `\VibeTrade\OptionPremiumLevels` is Ready with four local triggers: 08:40, 08:55, 09:10, and 09:25 CT. It runs SPY, QQQ, IWM, AAPL, and NVDA.

## Provenance Limitation

The real host probe succeeded, but reported:

- `feed_provenance: account_default_unverified`
- `provenance_qualified: false`
- `trade_history_complete: true`

Do not set `OPTION_PREMIUM_DATA_FEED=opra` until the account subscription and returned feed are actually verified. Alpaca distinguishes its subscribed OPRA feed from its free delayed/derived indicative feed. Until verified, Flip records `observed_unqualified`; the levels remain research context only.

The retained option condition codes can include complex or nonstandard prints. Do not silently filter them or interpret premium concentration as support/resistance until an official condition-code mapping and a preregistered forward test justify that treatment.

## Host Verification

- Focused tests: `64 passed`.
- `py_compile`: clean.
- Execution gate audit: `passed=true`, `issue_count=0`, `execution_enabled=false`.
- Risk fail-closed proof: `passed=true`, all 4 deterministic cases passed, `can_submit_orders=false`.
- `git diff --check`: clean except the existing Windows LF/CRLF notice.
- Scheduled task: Ready, four triggers.

Real SPY probe for 2026-07-16:

- 16 contracts queried independently.
- 966,987 prints aggregated.
- No truncated contracts.
- Top call premium strikes: 753, 752, 754, 751.
- Top put premium strikes: 752, 753, 751, 754.

These probe results prove collection and aggregation, not predictive edge.

## Claude Review Queue

1. Review completed-bar handling and retest invalidation/freshness semantics for look-ahead or timestamp mistakes.
2. Verify the Windows task trigger times remain aligned with the intended 09:40-10:25 ET research window through DST changes.
3. Confirm the Alpaca option-data subscription before qualifying any report as OPRA.
4. Build a read-only forward outcome comparison: raw ORB breakout versus retest-confirmed ORB, stratified by symbol, direction, time bucket, ATR ratio, dislocation z-score, and close-location.
5. Keep dislocation and premium levels advisory until the preregistered sample threshold, multi-day coverage, costs, and out-of-sample evidence support promotion.

## Explicit Non-Changes

- No real-money execution activation.
- No execution authorization changes.
- No contract-size increase.
- No stop/target/ratchet changes.
- No automatic 2R exit was added; existing Flip exit management remains authoritative.
- No premium-level or dislocation veto was added.

