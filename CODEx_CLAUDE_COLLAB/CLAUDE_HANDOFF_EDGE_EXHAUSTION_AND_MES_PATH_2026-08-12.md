# Edge Exhaustion and MES Path — Handoff to Codex
**Date:** 2026-08-12 (second handoff same session)
**Author:** Claude Code
**Orders submitted:** zero. **Live enablement changes:** zero. **Config mutations:** zero.

## Executive Summary

All options-based edge hypotheses for the flip bot have been tested and failed executable evaluation.
The search space is exhausted. The structural reason is clear: 0DTE OTM options carry bid-ask
spreads that consume every apparent signal before it reaches execution.

The correct next path is a **proprietary liquidity-response residual model for MES futures**,
as Codex identified mid-session. This requires TopstepX read-only order-book data collection
to start. Without that data, no model can be validated.

---

## What Was Built and Tested This Session

### Lab 1 — Exit Policy Replay (earlier session)
10 preregistered exit policies, 1,180 lifecycles. **All negative post-fee.**
Best: `time_stop_30m` at -1.84%.

### Lab 2 — Entry Limit Execution (earlier session)
4 fill policies. **All negative.** Passive limits selectively miss winners (+18-21% missed mean).

### Lab 3 — Filter Comparison (first_mark_gate, mid-based)
`first_mark_green` filter: +14.87% post-fee at midpoint. 59% win rate. Looked like real edge.

### Lab 4 — First-Mark Gate (Codex, executable ask-to-bid)
Same gate with executable prices. **All policies -4.82% to -5.12%.** Mid edge disappears entirely.

### Lab 5 — Spread + ATM Filter Lab (this session)
`research/spread_atm_filter_lab.py`, 10 preregistered filters across 1,204 lifecycles.

| Filter | n | dates | exec% | 2x% | top5-% | WR | PF | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| spread5_entry100 | 459 | 15 | **+0.54** | -0.96 | -5.99 | 42.3% | 1.03 | FAIL(3) |
| spread3_entry50 | 500 | 15 | -1.42 | -2.92 | -8.79 | 40.0% | 0.93 | FAIL(4) |
| entry_ge_200c | 493 | 15 | -1.57 | -3.07 | -7.46 | 42.4% | 0.91 | FAIL(4) |
| spread_le_5c | 736 | 19 | -3.27 | -4.77 | -10.42 | 39.0% | 0.84 | FAIL(4) |
| entry_ge_100c | 862 | 15 | -3.35 | -4.85 | -9.68 | 39.8% | 0.82 | FAIL(4) |
| spread_le_3c | 571 | 19 | -3.38 | -4.88 | -10.52 | 38.9% | 0.84 | FAIL(4) |
| baseline | 1204 | 19 | -5.02 | -6.52 | -11.64 | 38.2% | 0.75 | FAIL(4) |

`spread5_entry100` (spread ≤ 5c AND entry ≥ $1.00) reduces bleed from -5.02% to +0.54%.
**Does not survive doubled cost (-0.96%) or top-5-removed (-5.99%). Not an edge.**

---

## Why Options Cannot Be Fixed by Filtering

Codex's mid-session diagnosis (verbatim, preserved):

> An edge cannot be manufactured by adding indicators. It must come from at least one of:
> - Information other traders are not using.
> - Faster or cheaper execution.
> - Better conditional forecasting.
> - Better risk allocation.
> - A structural market premium.

The 0DTE OTM options problem is structural:
- Bid-ask spread: mean 4.83% of mid, p90 10.26%
- Theta at maximum decay rate
- IV crushes on non-events
- No informational advantage in an ORB directional signal

The `spread5_entry100` filter gets the spread down to ~$0.05 / ($1.00 × 2) = ~5% round-trip cost,
barely covering fees. There is nothing left for positive expectancy.

The first-mark momentum gate was +14.9% at midpoint because momentum continuation is real —
but you can't trade at midpoint. Paying the spread eliminates the signal.

---

## Option 2 — Intraday IV Spike Capture (Spec, Not Yet Built)

This is a 0DTE iron condor strategy targeting the opening IV compression, not yet in the codebase.

**Mechanism:**
- Open (9:30-9:45 ET): IV on SPY/QQQ 0DTE spikes due to overnight uncertainty
- By 10:30-11:00 ET: IV compresses 30-50% as the day's direction becomes clear
- Edge: sell the opening IV spike, collect decay, close before afternoon gamma risk

**Spec:**
```
Entry window: 9:35-9:45 ET
Instrument: SPY or QQQ 0DTE iron condor
Width: 1 standard deviation (ATM straddle price / underlying × 1.0)
Short strikes: ±0.5 SD from current price
Wing hedges: 2 strikes further OTM for defined risk
Credit required: >= $0.25 (ensures enough premium to cover spread)
Entry condition: VIX > 15, no FOMC/CPI within 2 hours
Exit: 50% profit OR 11:00 ET time stop OR 200% loss stop
Max 1 trade per day
```

**Why this might work:**
- Selling premium means the spread works FOR you (you receive ask, market maker pays bid)
- IV compression is structural — it happens every day, not directional
- Defined risk prevents blow-up

**Blocker:** No IC lifecycle data exists yet. Need 30+ resolved outcomes across 20+ dates
before any review gate evaluation. Shadow mode only initially.

**This is already partially implemented as `strategies/spy_iron_condor.py`** but at 21-30 DTE.
The 0DTE variant is different — faster entry/exit, smaller credit, intraday IV target.

---

## The Correct Next Path — Codex's MES Liquidity-Response Residual Model

Codex's full recommendation (preserved verbatim):

> Our fastest credible path is a proprietary liquidity-response residual model for MES:
> - Estimate how far price should move from aggressive buying/selling, volatility, spread, and depth.
> - Measure the residual between expected and actual movement.
> - Detect absorption when extreme flow produces unusually little movement and opposing liquidity replenishes.
> - Detect continuation when flow moves price efficiently and opposing depth disappears.
> - Trade only after confirmation when predicted return exceeds spread, fees, slippage, and an uncertainty buffer.
>
> This improves on the rejected fixed absorption rule because it is regime-normalized rather than
> relying on one impossible threshold combination. It also avoids 0DTE option spreads.
>
> The hard blocker is information: TopstepX credentials are absent, so we are not collecting
> depth, replenishment, cancellations, and signed trades. Existing candle and BBO history cannot
> validate this model.

### Build Sequence (Codex's recommendation, adopted)

1. **TopstepX read-only recorder activation** — collect raw order-book snapshots:
   depth (bid/ask size at each level), trade prints (signed aggressor), cancellations,
   replenishment events. Store to `data/mes_orderbook/YYYY-MM-DD.jsonl`.
   This is the information that does not exist in candle history.

2. **Causal depth/flow feature engine** — from raw book data, compute:
   - Signed aggressive flow per N-second window
   - Expected price displacement (flow × impact model)
   - Actual price displacement
   - Residual = actual − expected (absorption score)
   - Opposing depth replenishment rate post-flow

3. **Frozen liquidity-response model** — preregister thresholds before seeing outcomes:
   - Absorption threshold: residual < −X% of expected (price moved less than flow predicted)
   - Continuation threshold: residual > +X% AND opposing depth declines Y%
   - Uncertainty buffer: predicted return must exceed spread + fees + 1 SD of residual noise

4. **Walk-forward and doubled-cost evaluation** — same review gate framework as options labs:
   30 untouched shadow trades, 20 dates minimum, positive executable expectancy under doubled cost.

5. **One-MES Practice promotion** — only after gate passes, only on Practice account.

---

## What Codex Should Do Next

### Immediate (no new data required)
1. **Mark `flip_directional_0dte` as `research` status** in any feature/strategy registry.
   It has exhausted 5 independent evaluations. Do not schedule for live promotion.
   Continue shadow collection (shadow data is free, costs nothing to collect).

2. **Keep `spy_iron_condor.py` collecting shadow evidence.** It still has 0 resolved outcomes.
   The math-backed VRP edge there needs 100+ resolved outcomes before review gate opens.
   Do not stop it — just don't force-promote it.

3. **Do NOT build Option 2 (0DTE IC intraday) yet.** Needs infrastructure first.
   If Codex wants to scaffold the entry logic, do it shadow-only with zero execution authority.

### When TopstepX credentials are available
4. **Activate TopstepX read-only recorder** (build `agent/mes_book_recorder.py`):
   - Connects to TopstepX market data feed
   - Records depth, trades, cancellations per 1-second intervals
   - Writes to `data/mes_orderbook/YYYY-MM-DD.jsonl`
   - No execution authority, no order submission

5. **Build causal feature engine** (`research/mes_flow_features.py`):
   - Computes signed flow, impact model, residual, replenishment features
   - Read-only, fail-closed
   - Frozen feature set preregistered before any outcome data is attached

6. **Freeze the model spec** (write to `CODEx_CLAUDE_COLLAB/MES_LIQUIDITY_RESIDUAL_SPEC_VDATE.md`)
   before attaching any outcome labels. This prevents post-hoc fitting.

---

## What NOT to Do

| Action | Reason |
|---|---|
| Add more entry indicators to flip bot | Space exhausted, same structural spread problem |
| Build another filter on existing options corpus | 5 independent labs all fail executable test |
| Enable live execution on any options strategy | No strategy passes review gate |
| Auto-wire self-learning loop | Intentional read-only safety design |
| Build 0DTE IC strategy before TopstepX data | No outcome data to validate against |
| Raise position sizing | Nothing passes doubled-cost gate |

---

## Files Built This Session

| File | Purpose |
|---|---|
| `research/flip_filter_lab.py` | 9 universe filters vs midpoint returns (new) |
| `research/spread_atm_filter_lab.py` | 10 spread/ATM filters vs executable returns (new) |
| `research/first_mark_gate_lab.py` | 4 early-exit gate policies vs executable returns (Codex) |
| `data/flip_filter_lab_results.json` | Generated |
| `data/spread_atm_filter_lab_results.json` | Generated |
| `data/first_mark_gate_lab_results.json` | Generated |
| `strategies/flip_bot.py:3036` | `first_mark_momentum_not_confirmed` shadow exit gate (Codex) |
| `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_FLIP_BOT_EDGE_VERDICT_2026-08-12.md` | Prior handoff |
| `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_FIRST_MARK_MOMENTUM_GATE_2026-08-12.md` | Prior handoff |
| this handoff | Consolidates all findings, adopts MES path |

No live execution. No scheduler changes. No entry logic changes. No config mutations.

---

## Reproduction

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

python research\flip_filter_lab.py --print
python research\spread_atm_filter_lab.py --print
python research\first_mark_gate_lab.py --print
```
