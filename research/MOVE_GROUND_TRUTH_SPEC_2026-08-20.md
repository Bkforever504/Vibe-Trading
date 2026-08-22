# MOVE Universe Ground-Truth Specification

**Status:** frozen
**Kenny Approval:** approved
**Variant:** MEDIUM (canonical baseline)
**Approval prompt (Kenny, 2026-08-22):** "do everything, don't worry about the cost. We are here to create the best dashboard, give me the best trades so i can make money"
**Draft Author:** Claude (2026-08-22)
**Purpose:** Define what qualifies as a labeled "move" for the Detection Scorecard. Loaded by `scripts/move_universe_ground_truth.py` ONLY when this file contains both `Status: frozen` AND `Kenny Approval: approved`. Two sidecar variants (`_TIGHT` + `_LOOSE`) sit unfrozen for post-Monday A/B/C comparison — see §11.

---

## 1. Instrument Universe

| Symbol | Class | Session | Bar timeframe(s) |
|---|---|---|---|
| SPY | Equity ETF | 09:30–16:00 ET (RTH) | 5m, 15m, 1h, D |
| QQQ | Equity ETF | 09:30–16:00 ET (RTH) | 5m, 15m, 1h, D |
| IWM | Equity ETF | 09:30–16:00 ET (RTH) | 5m, 15m, 1h, D |
| MES | Micro E-mini S&P futures | 18:00 ET (prior) → 17:00 ET (RTH+ETH) | 5m, 15m, 1h, D |
| ES | E-mini S&P futures | 18:00 ET (prior) → 17:00 ET | 5m, 15m, 1h, D |
| NQ | E-mini Nasdaq futures | 18:00 ET (prior) → 17:00 ET | 5m, 15m, 1h, D |

ETH bars for futures flagged separately; grader must not blend RTH+ETH volume profiles.

---

## 2. What Qualifies as a "Move"

A labeled move is a directional price displacement that meets ALL of the following:

### 2.1 Magnitude threshold
- **Equity ETF (SPY/QQQ/IWM) 5m:** ≥ 0.30% net move within 12 bars (1 hour) from trigger candle close.
- **Equity ETF 15m:** ≥ 0.50% net move within 8 bars (2 hours).
- **Equity ETF 1h:** ≥ 0.75% net move within 6 bars (6 hours).
- **Equity ETF D:** ≥ 1.25% net move within 3 daily bars.
- **Futures MES/ES/NQ 5m:** ≥ 5 ES points (0.15%) within 12 bars.
- **Futures 15m:** ≥ 8 ES points within 8 bars.
- **Futures 1h:** ≥ 12 ES points within 6 bars.
- **Futures D:** ≥ 25 ES points within 3 daily bars.

### 2.2 Direction retention
- Net move must persist ≥ 60% of the horizon (i.e., peak favorable excursion holds for at least 60% of measurement window without giving back > 50%).

### 2.3 Minimum R-multiple achievability
- Given a stop placement of 0.5 × ATR14 at trigger, the move must reach ≥ 1.5R within horizon to count as a positive-labeled move.
- Anything < 1.5R = null label (no positive/negative — insufficient magnitude).

### 2.4 Directional label
- **Long-move (`+1`):** meets 2.1–2.3 upward.
- **Short-move (`-1`):** meets 2.1–2.3 downward.
- **No-move (`0`):** fails any of 2.1–2.3.

---

## 3. Trigger Bar Definition

A trigger bar is the candle at which a pattern detector would fire an entry:
- For continuation patterns (flag, ORB, BOS): trigger = breakout close bar.
- For reversal patterns (H&S, DT/DB, spring, CISD): trigger = confirmation close bar (not the signal bar itself).
- For candlesticks: trigger = confirmation candle close (bar after the signal candle).

Ground truth is measured **from trigger bar close forward**, never from the signal bar itself. This prevents look-ahead bias.

---

## 4. Session Boundary Rules

- Trigger bars must have `bar_close_ts` inside session (RTH for equity ETFs; RTH or explicit ETH-flagged for futures).
- Overnight gap for equity ETFs: does NOT count as a "move" — 09:30–10:00 ET first 30 min excluded from measurement horizon due to opening auction noise (still eligible for trigger, but horizon starts at 10:00 ET).
- Macro-event windows (CPI/FOMC/NFP release ±15 min): trigger bars in this window are labeled `excluded` regardless of downstream magnitude.

---

## 5. Data Source

- **Equity ETF bars:** Alpaca IEX + Alpaca SIP (SIP preferred if entitled; IEX-only bars flagged in `data_source` field).
- **Futures bars:** Databento MBO parquet aggregated to 5m/15m/1h/D. RTH boundary = 09:30–16:00 ET; ETH = all other times.
- **ATR14:** computed causally on the trigger bar's timeframe using prior 14 completed bars (no look-ahead).

---

## 6. Ground-Truth Ledger Schema

Each labeled trigger emits one row to `data/move_ground_truth_ledger.jsonl`:

```json
{
  "ts_utc": "2026-09-15T14:35:00Z",
  "trigger_bar_ts": "2026-09-15T14:30:00Z",
  "instrument": "SPY",
  "timeframe": "5m",
  "session": "RTH",
  "trigger_price": 555.42,
  "atr14": 0.68,
  "horizon_bars": 12,
  "horizon_end_ts": "2026-09-15T15:30:00Z",
  "peak_favorable_long": 0.42,
  "peak_favorable_short": 0.11,
  "peak_adverse_long": 0.09,
  "peak_adverse_short": 0.38,
  "realized_r_long": 1.72,
  "realized_r_short": -0.44,
  "label": 1,
  "label_reason": "long_move_1.72R_60pct_retention",
  "excluded": false,
  "excluded_reason": null,
  "data_source": "alpaca_iex",
  "spec_version": "2026-08-20"
}
```

---

## 7. Build Cadence

- Nightly (16:30 ET post-close): `scripts/build_move_ground_truth.py` (Codex Phase D) scans all instrument×TF pairs for the trading day, labels every candle, appends to ledger.
- Weekly (Sunday 09:00 CT via existing intake scheduler): recompute rolling 30-day ground-truth summary → `~/.vibe-trading/reports/move-ground-truth-summary.json`.

---

## 8. Coverage Delta Semantics (for detection scorecard)

- **Detected:** pattern grader fired an entry signal at trigger bar.
- **Labeled:** ground-truth ledger has a row for that bar with `label ∈ {+1, -1}`.
- **True positive (TP):** detected AND labeled same direction.
- **False positive (FP):** detected AND (label = 0 OR opposite direction).
- **False negative (FN):** NOT detected AND labeled.
- **True negative (TN):** NOT detected AND label = 0.

**Precision** = TP / (TP + FP)
**Recall** = TP / (TP + FN)
**Coverage delta** = (detected count − labeled count) / labeled count

A healthy grader: precision ≥ 0.55, recall ≥ 0.30, coverage delta in [−0.5, +2.0].

---

## 9. Frozen Contract

Once approved, the following are **immutable** without a new spec version (bumped `spec_version` field):
- Magnitude thresholds (§2.1)
- Direction retention rule (§2.2)
- R-multiple threshold (§2.3)
- Session boundaries (§4)
- ATR calculation method (§5)

Additive fields to §6 schema are allowed w/o version bump.

---

## 10. Approval — DONE

Kenny directed freeze via chat prompt on 2026-08-22. Markers flipped. Loader now active for MEDIUM variant.

## 11. A/B/C Variant Comparison (Post-Monday Evaluation)

Three threshold sets ship in parallel:

| Variant | File | Magnitude vs MEDIUM | Expected effect |
|---|---|---|---|
| TIGHT | `MOVE_GROUND_TRUTH_SPEC_TIGHT_2026-08-22.md` | +30% | Fewer labels, higher precision, lower recall. Best if MEDIUM too noisy. |
| **MEDIUM** (canonical) | `MOVE_GROUND_TRUTH_SPEC_2026-08-20.md` | baseline | Balanced. Frozen + loaded now. |
| LOOSE | `MOVE_GROUND_TRUTH_SPEC_LOOSE_2026-08-22.md` | -30% | More labels, higher recall, lower precision. Best if MEDIUM too sparse. |

**Sidecar variants stay unfrozen** — labels get computed nightly against all 3 for accountability, but only MEDIUM populates the canonical detection scorecard.

**Evaluation trigger:** after 10 trading days of live shadow data (~2026-09-05), run `scripts/compare_move_variants.py` (Codex Phase C follow-up) which reports:
- Label count per variant per instrument×TF
- Grader precision/recall using each variant as truth
- F1 score per variant
- Distribution of `realized_r` for labeled `+1`/`-1` moves per variant

**Promotion rule:** if TIGHT or LOOSE beats MEDIUM on F1 by ≥ 15% AND maintains ≥ 20 labels/instrument/day, swap canonical. Otherwise keep MEDIUM.

**Kenny approval required** to swap canonical variant — same fail-closed marker mechanism.

---

**Loader active. First real labels emit end of day 2026-08-25 (next trading day).**
