# Codex Handoff: P2 Options P&L Capture + Failure Taxonomy
From: Claude Code
Date: 2026-07-25
Session cost at handoff: ~$60 (stop here; build in Codex)
Prior handoff: `CODEX_HANDOFF_FROM_CLAUDE_2026-07-25_UPGRADES.md`

---

## Context Kenny Added (NEW since prior handoff)

Kenny asked: "What if we reversed the logic of the losing trades to actually win
the trade then study that process. Hone in on all of the losers to correct our
mistakes for said outcome. If you study every failed trade and improve the logic
every time, that should increase the win rate. Every and any which way you can
lose should have a counter measure depending on any market condition."

Claude's answer (summarized for Codex):
- The concept is sound. The trap is hindsight overfitting (415 attempts already logged).
- Right approach: categorize failures by type → test if systematic → pre-register
  countermeasure → shadow-observe ≥30 dates → only then nominate for promotion.
- Existing `self_learning_edge_loop.py` already imports `lifecycle_normalizer` but
  uses contaminated options P&L labels (12/13 closed records lack fill-derived P&L).
- Fix prerequisite order: P2 (clean labels) → wire learning reports → failure taxonomy.

Kenny then said: "do both, then give a handoff to Codex."
Claude read files, hit session cost ceiling. Build both tasks below.

---

## Task 1 — P2: Options Lifecycle P&L Capture

### What's wrong now

`~/.vibe-trading/options-trades.json` closed records look like:

```json
{
  "id": "ef549ea4-...",
  "status": "closed",
  "closing_reason": "profit target hit: +55.8% of credit",
  "net_credit": 0.52,
  "qty": 3,
  "strategy": "put_spread"
  // NO closing_filled_avg_price, NO realized_pnl_dollars
}
```

P&L is reverse-engineered from `closing_reason` regex text → contaminated labels.
`scripts/lifecycle_contamination_audit.py` confirmed: 12/13 closed options records
lack fill-derived P&L. The `lifecycle_normalizer.py` quarantines these as
`closed_without_resolvable_pnl`.

### What needs to be built

**In `strategies/iwm_options_bot.py`** — wire `closing_filled_avg_price` onto the
trade record when a closing order fills. The field `closing_filled_avg_price` is
already canonicalized on the *entry* side; do the same for the *exit*.

Specifically, find the section that sets `status: "closed"` on a trade (after
a closing order fills). At that point the Alpaca order object has:
- `filled_avg_price` (the closing execution price)
- `filled_qty`

Add these two fields to the trade record before writing it back to the state file:

```python
trade["closing_filled_avg_price"] = float(closing_order.filled_avg_price)
trade["closing_filled_qty"] = int(closing_order.filled_qty)
# Derived realized P&L for credit structures:
# net_credit was received as cash; closing debit is the buyback cost
# pnl = (net_credit - closing_filled_avg_price) * qty * 100
closing_price = float(closing_order.filled_avg_price)
net_credit = float(trade.get("net_credit") or 0)
qty = int(trade.get("qty") or 1)
trade["realized_pnl_dollars"] = round(
    (net_credit - closing_price) * qty * 100, 2
)
trade["pnl_source"] = "fill_derived"
```

For the entry side (debit structures like flip bot), the sign is already handled
by `_apply_entry_fill` (D1 fix from prior session). Mirror that pattern here.

**In `scripts/lifecycle_normalizer.py`** — update `normalize_options_record()`:
- If `pnl_source == "fill_derived"` and `realized_pnl_dollars` is present, use it.
- If absent but `closing_filled_avg_price` exists, compute from it.
- Only fall through to quarantine if both are missing.

**Target**: next 30 closed positions carry `pnl_source: "fill_derived"`.
Legacy 12/13 records stay quarantined (cannot be retroactively repaired).
Mark them explicitly: `"legacy_no_fill_pnl": true` in their normalized view.

**Tests to add** (`agent/tests/test_options_lifecycle_pnl.py`):
1. Closing fill sets `closing_filled_avg_price`, `realized_pnl_dollars`, `pnl_source`.
2. P&L correct for a put_spread: net_credit=0.52, closing_price=0.23, qty=3
   → pnl = (0.52-0.23)*3*100 = $87.00.
3. Normalizer accepts `pnl_source: "fill_derived"` and does NOT quarantine.
4. Normalizer quarantines record missing both `realized_pnl_dollars` and
   `closing_filled_avg_price`, sets `legacy_no_fill_pnl: true`.
5. Zero or negative closing price (expired worthless): pnl = net_credit * qty * 100.

---

## Task 2 — Failure Taxonomy Script

### Design

New file: `scripts/failure_taxonomy.py`

**Purpose**: Read all closed trades across all three bot families, classify each
loss into a repeatable failure category, tag by market regime at time of trade,
and output a ranked failure-mode report. Each systematic category (≥10 independent
instances) earns a pre-registration template for a countermeasure trial.

**Failure categories** (mutually exclusive, applied in order):

| Code | Name | Detection |
|------|------|-----------|
| `COST_CONSUMED_EDGE` | Spread/commission > underlying move | options only; `realized_pnl_dollars < 0` AND closing was within expected range of entry |
| `WRONG_DIRECTION` | Underlying moved against trade | from `lifecycle_normalizer` direction field vs underlying price change at entry vs close |
| `CORRECT_DIR_EARLY` | Right direction, wrong timing | direction correct but loss; entry before signal confirmation |
| `STOP_TOO_TIGHT` | Stopped out on noise, direction later correct | stop triggered; underlying recovered within DTE |
| `REGIME_MISMATCH` | Strategy designed for X regime, traded in Y | e.g., premium-selling in trending market |
| `EXECUTION_SLIPPAGE` | Fill price significantly worse than mid | fill vs NBBO captured at entry time |
| `UNKNOWN_LOSS` | None of the above | catch-all; flag for manual review |

**Market regime tags** (added to each record):

```python
{
  "vix_tier": "low|medium|high|extreme",   # <15 / 15-25 / 25-40 / >40
  "vix_at_entry": float,                    # from trade record
  "trend_score_at_entry": int | None,       # from flip_shadow or htf cache
  "session_phase": "pre_open|morning|midday|afternoon",
  "dte_bucket": "0dte|1dte|3_7dte|7_30dte|30_45dte",
}
```

**Output structure** (`~/.vibe-trading/reports/failure-taxonomy.json`):

```json
{
  "generated_at": "...",
  "total_closed": N,
  "total_losses": N,
  "excluded_quarantined": N,
  "by_category": {
    "WRONG_DIRECTION": {
      "count": N,
      "pct_of_losses": 0.NN,
      "systematic": true,
      "top_regime": "high_vix",
      "countermeasure_template": {
        "hypothesis": "Add VIX>25 direction-filter gate",
        "pre_register_before": "first forward signal",
        "shadow_min_dates": 30
      }
    },
    ...
  },
  "promotion_candidates": [],
  "records": [...]
}
```

**Read sources** (read-only, no writes to these files):
- `~/.vibe-trading/options-trades.json` (options family)
- `~/.vibe-trading/flip-trades.json` (flip family)
- `data/self_learning_mistake_ledger.jsonl` (cross-bot mistakes already logged)
- `scripts/lifecycle_normalizer.py` — consume normalized views, exclude quarantined

**Boundaries**:
- Diagnose only. Never mutates trade state.
- Quarantined records (12/13 options legacy) excluded from category counts.
- `promotion_candidates` list is empty by default; requires ≥10 independent
  instances AND human pre-registration before shadowing.
- No new edges promoted automatically.

**Tests** (`agent/tests/test_failure_taxonomy.py`):
1. Record with `realized_pnl_dollars < 0` and NBBO spread > move → `COST_CONSUMED_EDGE`.
2. Record with correct VIX tag from `vix_at_entry`.
3. Quarantined records excluded from category counts.
4. `by_category` sums to `total_losses` (no double-counting).
5. `systematic` flag requires count ≥ 10.

---

## Build Order

1. Task 1 first (P2 P&L capture) — cleans the labels.
2. Task 2 second (failure taxonomy) — consumes clean labels.
3. Run `python -m pytest agent/tests/test_options_lifecycle_pnl.py agent/tests/test_failure_taxonomy.py -q`
4. Run `python scripts/lifecycle_contamination_audit.py` — confirm quarantine
   count shrinks on new trades, legacy stays documented.
5. Run `python scripts/failure_taxonomy.py` — confirm report generates, 0 items
   in `promotion_candidates` (not enough data yet).

---

## Boundaries (unchanged)

No live trading; no purchases; MES task stays disabled; champions frozen;
consumed periods stay consumed; one active task per STATUS.md;
preserve dirty worktree; human-only promotion.

---

## Verification Baseline (from prior handoff)

Signal-stack health/alignment (16), lifecycle normalizer (10), green-day patches
(6) + lab (11), fill truth (7), confidence gate (20), gate outcomes (2), options
replay (6), Robinhood safety (26), probe (4). `execution_gate_audit.py` exit 0.

Add new suites: `test_options_lifecycle_pnl.py` (5 tests),
`test_failure_taxonomy.py` (5 tests). Total target: ~3476+ pass.
