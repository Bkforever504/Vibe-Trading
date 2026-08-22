# MOVE Universe Ground-Truth Specification — TIGHT Variant

**Status:** draft
**Kenny Approval:** pending
**Variant:** TIGHT (sidecar, +30% magnitude vs canonical MEDIUM)
**Purpose:** A/B/C comparison candidate. Fewer labels, higher precision, lower recall. Compared to MEDIUM after 10 trading days.

> This sidecar is NOT loaded by `scripts/move_universe_ground_truth.py` — canonical is MEDIUM. Labels compute nightly for evaluation only. To promote, run `scripts/compare_move_variants.py` and flip markers here if F1 beats MEDIUM by ≥ 15%.

---

## 1. Instrument Universe

Same as MEDIUM canonical (§1 of `MOVE_GROUND_TRUTH_SPEC_2026-08-20.md`).

## 2. What Qualifies as a "Move" — TIGHT thresholds

### 2.1 Magnitude threshold (30% tighter than MEDIUM)
- **Equity ETF 5m:** ≥ 0.40% net move within 12 bars
- **Equity ETF 15m:** ≥ 0.65% within 8 bars
- **Equity ETF 1h:** ≥ 1.00% within 6 bars
- **Equity ETF D:** ≥ 1.65% within 3 daily bars
- **Futures 5m:** ≥ 7 ES pts within 12 bars
- **Futures 15m:** ≥ 11 ES pts within 8 bars
- **Futures 1h:** ≥ 16 ES pts within 6 bars
- **Futures D:** ≥ 33 ES pts within 3 daily bars

### 2.2 Direction retention
- ≥ 70% of horizon (vs 60% MEDIUM). Peak favorable holds w/o giving back > 40%.

### 2.3 Minimum R-multiple
- ≥ 2.0R (vs 1.5R MEDIUM). Stop = 0.5 × ATR14 at trigger.

### 2.4 Directional label
Same as MEDIUM: `+1` / `-1` / `0`.

## 3–9

Same as MEDIUM canonical (see `MOVE_GROUND_TRUTH_SPEC_2026-08-20.md`).

## 10. Expected Impact vs MEDIUM

| Metric | MEDIUM (baseline) | TIGHT (this) | Rationale |
|---|---|---|---|
| Labels per day per instrument×TF | ~15-30 | ~5-12 | 30% tighter magnitude + 70% retention filter |
| False positive rate on grader | baseline | -30% expected | Cleaner "real move" definition |
| False negative rate on grader | baseline | +30-50% expected | Misses smaller valid setups |
| Best for | balanced | high-conviction A-grade validation | Fewer edge cases muddy the promotion pipeline |

## 11. Promotion Condition

Swap canonical to TIGHT if AFTER 10 trading days:
- TIGHT F1 score beats MEDIUM F1 by ≥ 15%
- TIGHT still produces ≥ 20 labels/instrument/day (to avoid statistical starvation)
- Grader precision improves ≥ 10 percentage points

---

**Kenny sign-off (only if TIGHT wins A/B/C evaluation):**

```
Status: frozen
Kenny Approval: approved
```
