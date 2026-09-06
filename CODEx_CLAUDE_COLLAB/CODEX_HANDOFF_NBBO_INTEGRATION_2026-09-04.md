# Codex Handoff — NBBO Integration (Databento key rotated + live)

**Date**: 2026-09-04
**Author**: Claude (spec)
**Executor**: Codex
**Depends on**: existing `scripts/fetch_databento_options_nbbo.py`, `scripts/premarket_thesis_shadow.py`, `scripts/institutional_confluence_shadow.py`, `scripts/governed_shadow_decision.py`
**Mode**: shadow-only. NBBO evidence card only. No execution authority. Fail-honest on missing data.

## Context

User rotated Databento key. Live and available in `agent/.env` as `DATABENTO_API_KEY`. Previously assumed missing; now real. Handoff #1 WS3 stub returned `status: "not_configured"` — now must be replaced with actual NBBO fetch + integration.

**Bright line**: NBBO evidence is a critic card, never a decision authority. Same rules as institutional_confluence_shadow.

## Non-negotiable invariants (inherit)

1. `execution_enabled=false`, `can_submit_orders=false` everywhere.
2. NBBO card can veto (add blocker) but cannot un-veto or override deterministic gate.
3. Every NBBO fetch logged: dataset, symbols, timeframe, cost tokens, latency, response hash, timestamp.
4. Daily cost cap. When budget exhausted → `status: "budget_exceeded"`, pipeline continues without NBBO.
5. When Databento API unavailable → `status: "missing"`, no fabrication from OHLCV.
6. Freshness gate: any quote older than 60 seconds is stale, not fresh.
7. `order_authority_invariant` must return `violations=0`.

---

## Workstream 3-real — Live NBBO integration

### 3a. Verify + harden existing NBBO fetch

**Investigate** `scripts/fetch_databento_options_nbbo.py`:
- Confirm it reads `DATABENTO_API_KEY` from `agent/.env`.
- Confirm dataset is `OPRA.PILLAR` (top-of-book NBBO).
- Confirm cost tracking: bytes fetched, credits consumed per call.
- Add daily USD budget cap via env `DATABENTO_DAILY_USD_BUDGET=5.00`. When projected next call exceeds budget → return `status: "budget_exceeded"`.
- Add call ledger `~/.vibe-trading/data/databento_call_ledger.jsonl` with per-call audit rows (dataset, symbols, start, end, bytes, credits, cost_usd, latency, response_hash, timestamp).
- Cache session: within 60 seconds, identical symbol+timeframe request returns cached response (no billable refetch).

**Test** `agent/tests/test_databento_nbbo_client.py`:
- Missing key → `status: "not_configured"`, no HTTP.
- Over-budget → `status: "budget_exceeded"`, no HTTP.
- Timeout mock → `status: "timeout"`, ledger row.
- Cache hit within 60s → no billable call, cached response returned.
- Cost accumulation across day → correctly enforces daily cap.

### 3b. Wire NBBO into premarket_thesis_shadow.py

**Current state**: `scripts/premarket_thesis_shadow.py` runs premarket window and emits `status: "outside_window"` / `theses: []` when no NBBO. Now must consume real NBBO.

**Implement**:
- Between 08:00–09:25 ET, fetch NBBO for SPY, QQQ, IWM 0DTE + weekly ATM ±5% puts/calls.
- Compute per-symbol:
  - `put_call_dollar_premium_ratio` — Σ(put mid-price × ask_size) / Σ(call mid-price × ask_size). Ratio >1.5 → put-heavy.
  - `skew_5pct` — IV of 5%-OTM put minus IV of 5%-OTM call. Positive → skew fear.
  - `unusual_prints` — trades > $50k premium in last 30 minutes. List with strike, side, size, premium.
  - `atm_iv_change_since_prior_close` — flag if ATM IV moved >20% vs prior close.
  - `net_gamma_estimate` — Σ(gamma × OI × 100 × spot) at nearest expiry. Sign indicates dealer positioning.
- Emit thesis card only when ≥2 of {put_call_ratio, skew, unusual_prints} align in same direction.

**Card schema** (extends existing):
```json
{
  "symbol": "SPY",
  "direction": "LONG|SHORT|NO_BIAS",
  "conviction": "low|medium|high",
  "evidence_summary": "put/call $ ratio 2.4, skew +8pts, 3 unusual put prints >$75k",
  "evidence_numeric": {
    "put_call_dollar_premium_ratio": 2.4,
    "skew_5pct": 8.2,
    "unusual_prints_count": 3,
    "unusual_prints_dollar_total": 340000,
    "atm_iv_change_since_prior_close_pct": 12.5,
    "net_gamma_estimate": -450000000
  },
  "sources_used": ["databento_opra_nbbo"],
  "as_of": "<UTC Z>",
  "expires_at_et": "10:00",
  "fresh": true,
  "execution_enabled": false,
  "can_submit_orders": false
}
```

**Discord routing**: `[PREMARKET THESIS · NBBO]` OBSERVE-only. No SIMULATE/ARMED. Prefix distinguishes from deterministic premarket signals.

**Fail-honest**:
- Databento status `not_configured`, `budget_exceeded`, `timeout`, or `error` → card emits `status: "missing"`, `sources_used: []`, no numeric evidence fabricated.
- Any quote older than 60s → skip that leg, do not include in ratio.

**Test** `agent/tests/test_premarket_thesis_shadow_nbbo.py`:
- Real Databento fixture (frozen response) → thesis card populated with numeric evidence.
- Missing NBBO → NO_BIAS across all symbols.
- 1 of 3 signals aligned → NO_BIAS (requires ≥2).
- Stale quotes filtered from ratio.

### 3c. Wire NBBO into institutional_confluence_shadow.py

**Current state**: `scripts/institutional_confluence_shadow.py:163` lists `nbbo_options_flow` as unavailable with `reason: "no_verified_normalized_feed"`. Replace with real fetch.

**Implement**:
- Same Databento client. Intraday cadence.
- For each confirmed candidate symbol + direction, compute post-signal NBBO signature:
  - `directional_flow_bias`: LONG if calls receiving > puts on ask side; SHORT if inverse.
  - `flow_contradicts_candidate`: true if NBBO bias opposes candidate direction.
  - `unusual_prints_this_session`: count + $ total in candidate direction.
- Card:
```json
{
  "name": "nbbo_options_flow",
  "available": true,
  "fresh": true,
  "observed_at": "<Z>",
  "age_seconds": 12.3,
  "status": "aligned|contradicts|neutral",
  "direction": "LONG|SHORT|NEUTRAL",
  "contradicts_candidate": true|false,
  "facts": {
    "directional_flow_bias": "SHORT",
    "unusual_prints_count": 5,
    "unusual_prints_dollar_total": 620000,
    "put_call_ask_ratio": 1.8
  },
  "independent_source": true,
  "limitations": "OPRA NBBO snapshot; not sequenced tape trade attribution"
}
```

Now `independent_sources_available >= 2` can trigger `confluence_observed` legitimately when NBBO agrees with CZT or GEX.

**Test** `agent/tests/test_institutional_confluence_nbbo.py`:
- NBBO SHORT flow + LONG candidate → `contradicts_candidate: true` → `recommendation: "contradiction_observed"`.
- NBBO agreement + GEX agreement → `independent_sources_available: 2` → `recommendation: "confluence_observed"`.
- NBBO stale → `available: false`, no bias, no fabrication.

### 3d. Runner integration

**Add to `scripts/run_intraday_opportunity_radar.ps1`**:
- Existing `institutional_confluence_shadow` step now consumes live NBBO — no new step needed, just ensure it runs after alerts + before governed decision.

**Add scheduled task** for premarket:
- `scripts/register_premarket_thesis_task.ps1` — trigger daily 08:00 ET, single run.
- Task runs `python scripts/premarket_thesis_shadow.py`.
- 10-minute runtime limit. Wake to run: true. Run whether user logged on: true.

### 3e. Dashboard integration

**Extend** `scripts/generate_dashboard.py`:
- New panel "NBBO Options Flow" showing:
  - Today's Databento cost + remaining daily budget.
  - Latest per-symbol flow bias with age.
  - Unusual prints table (last 20).
  - Premarket thesis card if within expiry window.
- Show `missing` explicitly if API status is not `ok`. Never render fabricated numbers.

---

## Required checks

```powershell
python -m py_compile scripts/fetch_databento_options_nbbo.py scripts/premarket_thesis_shadow.py scripts/institutional_confluence_shadow.py scripts/governed_shadow_decision.py scripts/generate_dashboard.py
python -m pytest agent/tests/ -q -k "databento or nbbo or premarket_thesis or institutional_confluence"
python scripts/order_authority_invariant.py
git diff --check
```

## Deliverable back to Claude

Report with:
- Files touched (path:line)
- Test counts
- Sample Databento call ledger rows (3 real, 1 budget_exceeded, 1 timeout)
- Sample premarket thesis card populated from real NBBO
- Sample institutional_confluence card showing NBBO source with `available: true, fresh: true`
- Daily cost consumed on smoke test (should be <$0.50)
- Invariant status (must be `violations=0`)
- Confirmation that `execution_enabled` is nowhere `true`

---

## What NBBO integration is NOT allowed to do

- Decide entries or exits
- Size trades
- Route past deterministic gate
- Mutate any threshold or config
- Backfill missing NBBO with OHLCV-derived guesses
- Cache stale data past 60 seconds for freshness-critical fields
- Exceed daily budget cap
- Persist raw Databento payloads to git (audit ledger yes; full response bodies no — hash them)

## What NBBO IS allowed to do

- Add a blocker `nbbo_flow_contradicts_direction` when directional flow opposes candidate
- Elevate `institutional_confluence` from `insufficient_independent_evidence` to `confluence_observed` when it agrees with GEX or CZT
- Emit premarket OBSERVE thesis with numeric NBBO evidence quoted from payload
- Show cost + freshness on dashboard

## Cost expectations

- Databento OPRA NBBO snapshot: roughly $0.001-0.005 per symbol per fetch depending on time range.
- Premarket (once daily × 3 symbols): ~$0.03/day.
- Intraday confluence (~1 fetch per candidate × 5-15 candidates × 40 cadence runs): ~$1-3/day.
- Daily cap `$5.00` gives >2x headroom. If daily cost approaches cap, cache TTL should extend.

## Failure modes handled

- API key invalid → `not_configured` on every call, no crashes.
- API rate limit → `http_429`, exponential backoff, then `budget_exceeded`.
- Response schema drift → fixture replay diff test flags it before promotion.
- Silent vendor model update → not applicable (Databento is data, not model). Schema stability is contractual.
- Local DNS failure → `NameResolutionError`, ledger row, pipeline continues.

## Why this actually matters

Per shadow-consensus-blocker-audit, 11 of 12 symbols show negative expectancy on directional intraday. NBBO options flow is the only unlocked data source that could plausibly reveal edge not visible in OHLCV — because it captures institutional footprints before they appear on the tape. This handoff installs the plumbing. Whether it produces edge is a forward-session question the A/B evaluator (handoff #2 WS15) will answer.

No promises. Just plumbing installed correctly.
