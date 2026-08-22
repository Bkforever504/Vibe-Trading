# MOVE Universe Ground-Truth Specification — LOOSE Variant

**Status:** draft
**Kenny Approval:** pending
**Variant:** LOOSE (sidecar, -30% magnitude vs canonical MEDIUM)
**Purpose:** A/B/C comparison candidate. More labels, higher recall, lower precision. Compared to MEDIUM after 10 trading days.

> This sidecar is NOT loaded by `scripts/move_universe_ground_truth.py` — canonical is MEDIUM. To promote, run `scripts/compare_move_variants.py` and flip markers here if F1 beats MEDIUM by ≥ 15%.

---

## 1. Instrument Universe

Same as MEDIUM canonical.

## 2. What Qualifies as a "Move" — LOOSE thresholds

### 2.1 Magnitude threshold (30% looser than MEDIUM)
- **Equity ETF 5m:** ≥ 0.20% net move within 12 bars
- **Equity ETF 15m:** ≥ 0.35% within 8 bars
- **Equity ETF 1h:** ≥ 0.55% within 6 bars
- **Equity ETF D:** ≥ 1.00% within 3 daily bars
- **Futures 5m:** ≥ 4 ES pts within 12 bars
- **Futures 15m:** ≥ 6 ES pts within 8 bars
- **Futures 1h:** ≥ 9 ES pts within 6 bars
- **Futures D:** ≥ 20 ES pts within 3 daily bars

### 2.2 Direction retention
- ≥ 50% of horizon (vs 60% MEDIUM). Peak favorable holds w/o giving back > 60%.

### 2.3 Minimum R-multiple
- ≥ 1.0R (vs 1.5R MEDIUM). Stop = 0.5 × ATR14 at trigger.

### 2.4 Directional label
Same as MEDIUM.

## 3–9

Same as MEDIUM canonical.

## 10. Expected Impact vs MEDIUM

| Metric | MEDIUM (baseline) | LOOSE (this) | Rationale |
|---|---|---|---|
| Labels per day per instrument×TF | ~15-30 | ~40-80 | 30% looser magnitude + 50% retention |
| False positive rate on grader | baseline | +20-40% expected | Grader fires on smaller moves that count as "real" |
| False negative rate on grader | baseline | -20-40% expected | Catches more valid setups grader missed |
| Best for | balanced | scalp / high-frequency A-grade candidates | Statistical significance faster w/ more labels |

## 11. Promotion Condition

Swap canonical to LOOSE if AFTER 10 trading days:
- LOOSE F1 score beats MEDIUM F1 by ≥ 15%
- Grader precision doesn't collapse (stays ≥ 0.45)
- Recall improves ≥ 15 percentage points

---

**Kenny sign-off (only if LOOSE wins A/B/C evaluation):**

```
Status: frozen
Kenny Approval: approved
```
