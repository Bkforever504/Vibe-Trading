# Daily Map + 3-Minute Confluence Shadow Implementation

**Date:** 2026-09-04  
**Authority:** shadow alerts and simulated lifecycle only; no broker orders  
**Source:** user-supplied screenshots from a live Trader Barbie trading Zoom, plus the previously reviewed public VVS material

## Observable method

The screenshots support a top-down workflow, not a reproducible proprietary
indicator formula:

1. Use completed daily bars to establish directional context and pre-map levels.
2. Carry the map to a lower timeframe.
3. Alert while price approaches or first interacts with a level.
4. Require a completed lower-timeframe acceptance, rejection, reclaim, or loss
   before a confirmed shadow candidate.
5. Use adjacent pre-existing levels for invalidation and targets.

Visible labels include calls, puts, overnight, magnet, magnitude, numbered
targets, prior-week references, and a dynamic ribbon. The screenshots do not
disclose the formulas for the proprietary labels or ribbon. They must never be
silently reconstructed from hindsight.

## Dependency graph

1. **MAP-01 — reproducible level map**
   - Universe: SPY, QQQ, IWM, AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA.
   - Public levels use completed-bar prior-day/prior-week/session references.
   - Optional custom levels require explicit source, creation timestamp,
     session date, label, price, and `external_unverified` provenance.
2. **MAP-02 — causal three-minute lifecycle** (depends on MAP-01)
   - Build only completed 3-minute bars from timestamped 1-minute observations.
   - States: WATCH, ARMED, CONFIRMED, LATE, INVALIDATED.
   - Preserve first eligibility and decision-available timestamps.
3. **MAP-03 — state-change alerts** (depends on MAP-02)
   - Alert early WATCH/ARMED states directly once per state signature.
   - Route CONFIRMED candidates through independent evidence cards and the
     deterministic veto/risk gate before the governed shadow alert.
   - Undelivered transitions remain retryable and unacknowledged.
4. **MAP-04 — dashboard evidence** (depends on MAP-01/02)
   - Show daily bias, nearest level and provenance, distance, 3m state,
     trigger, invalidation, next target, timestamp, and freshness.
   - Missing or stale evidence is ATTENTION, never healthy.
5. **MAP-05 — runner integration and outcome learning** (depends on MAP-03/04)
   - Refresh before the governed decision spine.
   - Append evidence without changing rank, size, or execution authority.
   - Compare alert latency, MFE/MAE, target/stop outcomes, and missed moves by
     symbol, level family, daily bias, state, and time bucket.

## Non-negotiable controls

- No screenshot-derived number becomes a live level for a future session.
- No proprietary `magnet`, `magnitude`, calls/puts, or ribbon formula is guessed.
- Custom levels expire by declared session and remain separately attributed.
- A daily bias cannot create a trade; it is context for a lower-timeframe event.
- Unfinished bars, stale quotes, malformed maps, and missing provenance fail
  closed for confirmation.
- WATCH and ARMED visibility must not be suppressed merely because the family
  is unvalidated; all activity remains shadow/simulated.
- No A+/B+ score, sizing, promotion, or broker authority changes from this lane.

## Acceptance criteria

- Deterministic tests cover level construction, 3m completion boundaries,
  each lifecycle transition, late-chase rejection, custom-level validation,
  alert retry/idempotency, stale/malformed reports, and dashboard escaping.
- SPY/QQQ/IWM are always represented; partial MAG7 data remains explicit.
- Every confirmed record contains symbol, direction, level, trigger,
  invalidation, target, bar-completed timestamp, provenance, and no-order flags.
- The scheduled runner produces the report before candidate normalization and
  regenerates the dashboard afterward.

## Completion evidence

- Implemented on 2026-09-04 across the core/MAG7 universe.
- Live premarket check: 10 requested / 10 available, zero data errors.
- Full manual runner check: 448 discovered, 160 evaluated, one output row
  appended, zero scanner errors, normalized run envelope healthy with breaker
  closed.
- Verification: 113 focused tests passed; order-authority violations = 0;
  Python compilation and PowerShell parsing clean.
- Independent final review: no remaining P0/P1 findings.
