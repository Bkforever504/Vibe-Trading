# Codex — CISD Promotion Tracker

Copy-paste into fresh Codex session.

---

**Task:** Wire the CISD (Change In State of Delivery) promotion counter so the dashboard shows real-time progress toward validating the CISD hypothesis. Non-execution work. Non-destructive.

**Repo:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

**Context:** CISD detector shipped previously. Currently labeled `unvalidated_pattern_hypothesis`. Promotion gate: ≥ 100 outcomes AND ≥ 30 unique dates AND conservative Wilson lower-bound win rate ≥ 0.55 AND positive Brier skill vs base rate.

**Deliverables:**

1. **Outcome resolver — `scripts/pattern_grader_outcome_resolver.py`:**
   - Reads `data/pattern_grader_log.jsonl` rows where `outcome_5m/15m/60m/eod` are null and `trigger_bar_ts + horizon` has passed.
   - Pulls forward bars via existing Alpaca / Databento loaders.
   - Computes realized R multiple, hit_t1, hit_t2, stopped, expired.
   - Rewrites row w/ outcome fields filled. Append-only ledger discipline: use companion `data/pattern_grader_outcomes.jsonl` if in-place edit not idempotent.

2. **CISD promotion counter — `scripts/cisd_promotion_tracker.py`:**
   - Aggregates all rows w/ `pattern_id == "cisd_bullish"` or `"cisd_bearish"` from ledger.
   - Emits `~/.vibe-trading/reports/cisd-promotion-status.json`:
     ```json
     {
       "n_outcomes": 47,
       "n_unique_dates": 18,
       "win_rate_raw": 0.617,
       "wilson_lower_bound_95": 0.478,
       "brier_score": 0.198,
       "brier_baseline": 0.250,
       "brier_skill": 0.208,
       "gate_status": "pending",
       "gate_reasons_pending": ["n_outcomes < 100", "n_unique_dates < 30"],
       "eligible_for_validated_promotion": false,
       "last_updated_utc": "2026-08-22T21:30:00Z"
     }
     ```

3. **Frontend surface — extend `frontend/src/components/detection/DetectionTab.tsx`:**
   - Add "CISD Hypothesis Progress" card w/ 4 stat pills:
     - `n_outcomes / 100` w/ progress bar
     - `n_unique_dates / 30` w/ progress bar
     - Wilson lower bound (green ≥ 0.55, yellow 0.45-0.55, red < 0.45)
     - Brier skill (green > 0, red ≤ 0)
   - Big status pill: `unvalidated_pattern_hypothesis` (yellow) or `validated_pattern` (green) once all 4 gates pass.
   - Source: `~/.vibe-trading/reports/cisd-promotion-status.json` via existing `api.ts` pattern.

4. **Auto-flip logic — `scripts/promote_validated_patterns.py`:**
   - Reads promotion status JSON.
   - If `eligible_for_validated_promotion == true`, updates `research/pattern_taxonomy.json` for that pattern_id: sets `governance_status: "validated_pattern"` (was `unvalidated_pattern_hypothesis`).
   - Append audit row to `data/pattern_promotion_ledger.jsonl` w/ ts, pattern_id, prior_status, new_status, gate_snapshot.
   - Idempotent: no-op if already validated.
   - Runs nightly via scheduler.

5. **Scheduler wiring — `scripts/register_cisd_tracker_tasks.ps1`:**
   - `PatternGrader-OutcomeResolver` — daily 16:35 ET
   - `CISD-PromotionTracker` — daily 16:40 ET
   - `PromoteValidatedPatterns` — daily 16:45 ET (runs after tracker)
   - All idempotent.

6. **Tests:**
   - `agent/tests/test_pattern_grader_outcome_resolver.py` — synthetic ledger rows, verify outcome fields fill correctly, no look-ahead
   - `agent/tests/test_cisd_promotion_tracker.py` — Wilson bound math, Brier calc, gate logic edge cases (n=99, n=100, wilson 0.549 vs 0.551)
   - `agent/tests/test_promote_validated_patterns.py` — idempotent, correct taxonomy edit, ledger row appended
   - `frontend/src/components/detection/DetectionTab.test.tsx` — new CISD progress card renders w/ mock data

**Non-negotiables (all Phase A/B/C hold):**
- `execution_enabled=false`, `can_submit_orders=false`
- No bot bodies, no signal registry, no credentials, no canonical JSONL mutations
- `execution_gate_audit.py` must stay at 0 issues after this work
- Fail-closed: if outcome data source unavailable, log warning + skip row, do NOT fabricate outcome
- Deterministic: outcome resolver must produce identical results on replay

**Success criteria:**
- All new tests pass
- Full agent suite delta ≤ +10 tests (no regression)
- Frontend suite delta ≤ +5 tests
- Prod build green
- `cisd-promotion-status.json` emits w/ current state (likely n_outcomes=0 until grader runs live Monday)
- `execution_gate_audit.py`: 0 issues
- $0 external cost

**Halt after step 6.** Report: files created, test delta, first tracker output, any pattern already promoted, blockers.

Begin w/ step 1.
