# Codex Handoff: Adversarial Review Fixes — Verified Trader Pipeline
From: Claude Code
Date: 2026-07-25
Session cost ceiling hit at $61.31 — handing remaining fixes to Codex.

## Review Verdict

Passed 5 of 10 attack vectors clean. 4 defects found. 1 already fixed.

---

## Already Applied by Claude (D2)

`scripts/verified_trader_intake.py` line ~33 — `SECRET_KEY_FRAGMENTS` now includes
`"api-key"` and `"x-auth"` so hyphenated header-style keys (`x-api-key`,
`x-auth-token`, `api-key`) are caught by the sanitizer.

---

## Remaining Fixes for Codex

### D1 — event_type inflation from non-broker sources (medium)

**Attack**: A `tradingview_webhook` or `collective2_signal` payload that sends
`"event_type": "outcome"` increments `resolved_outcome_count` in the profile
summary toward the 30-gate (`status = "adversarial_review_required"`) without
any broker linkage. `broker_verified_history` stays False, but the status
becomes misleading.

**Fix** in `normalize_record()` — add this to the `quarantine_reasons` block:

```python
# Non-broker sources may not self-report outcomes; they can only be signals/fills.
if (
    canonical["event_type"] == "outcome"
    and not policy.get("broker_linked")
):
    quarantine_reasons.append("outcome_claimed_by_non_broker_source")
```

Location: `scripts/verified_trader_intake.py`, inside `normalize_record()`,
after the existing `completeness_below_0_70` check (around line 478).

**Test** to add in `agent/tests/test_verified_trader_intake.py`:
```python
def test_non_broker_outcome_quarantined():
    record = normalize_record(
        {"event_type": "outcome", "trader_id": "t1", "source_timestamp": "2026-07-01T12:00:00Z",
         "symbol": "SPY", "action": "BUY", "price": 100.0, "quantity": 1, "realized_pnl": 50.0},
        source_type="tradingview_webhook",
        source_id="test",
        consent_ref="consent-001",
    )
    assert record["safety"]["quarantined"]
    assert "outcome_claimed_by_non_broker_source" in record["safety"]["quarantine_reasons"]
```

---

### D3 — fingerprint collision is silent (low)

**Attack**: A source reuses `external_id` values (intentionally or not). The
second record with the same fingerprint is silently dropped with no warning.
A cherry-picking trader could suppress losing records by controlling external_id.

**Fix** in `append_records()` — return a `collision_count` distinct from
`duplicate_count`:

Current:
```python
    return {
        "accepted": len(accepted),
        "duplicates": duplicate_count,
        ...
    }
```

Change to track collisions separately. A "collision" is when the fingerprint
exists but the incoming record has a different non-empty `external_id` that
produced the same fingerprint (this is the suspicious case). Regular duplicates
(same source re-submitted) are expected. Simple approach: just rename
`duplicate_count` → keep it, but print a warning to stderr when
`duplicate_count > 0` on broker-linked sources:

```python
    if duplicate_count > 0:
        import sys
        broker_dupes = sum(
            1 for record in records
            if str(record.get("fingerprint") or "") in existing
            and record.get("source", {}).get("broker_linked")
        )
        if broker_dupes > 0:
            print(
                f"WARNING: {broker_dupes} broker-linked record(s) were deduplicated "
                "(fingerprint already present). Verify no losing records are suppressed.",
                file=sys.stderr,
            )
```

---

### D4 — `broker_verified_history` misleads on coverage (advisory)

**Attack**: 30 cherry-picked winning trades satisfy `broker_verified_history = True`
without any proof of complete account coverage (no gap check, no date range
manifest, no account-opening date check).

**Fix** — rename field and add a coverage placeholder:

In `_profile_summary()` replace:
```python
broker_verified_history = len(clean_broker_outcomes) >= 30
```
with:
```python
broker_outcome_count_sufficient = len(clean_broker_outcomes) >= 30
coverage_verified = False  # Requires P0 completeness manifest (not yet built)
```

Update the returned dict: replace `"broker_verified_history"` key with
`"broker_outcome_count_sufficient"` and add `"coverage_verified": coverage_verified`.

Update `_legacy_profile()` which references `profile["broker_verified_history"]`:
```python
"verified": bool(profile.get("broker_outcome_count_sufficient") and profile.get("coverage_verified")),
```
This makes `verified=False` for all traders until the P0 completeness proof
is built — which is correct.

---

## Confirmed Clean (no action needed)

1. Source tier inflation: `base_evidence_score` is policy-bound, not payload-controlled. ✓
2. Option-direction inference: `option_right` stored only, never used to infer direction. ✓
3. Missing consent entering statistics: quarantine gates are tight. ✓
4. Timestamp look-ahead: negative latency → `timestamp_paradox` quarantine. ✓
   (Advisory: CLI `--observed-at` can be set to source_timestamp for latency=0,
   timeliness_score=10. Low risk since CLI is operator-controlled.)
5. No trading client in webhook. ✓
6. Live-shadow market price gate: double-checked at both eligibility and export. ✓
7. Production inputs not overwritten. ✓

---

## Test Count Target After Fixes

Current: 77 focused tests pass.
Add: 1 test for D1 (non_broker_outcome_quarantined).
New target: 78+ focused tests pass.
`execution_gate_audit.py` must still exit 0.

---

## Boundaries (unchanged)

No live trading. No auto-promotion. No paid subscriptions without Kenny approval.
MES task disabled. Human approval mandatory.
