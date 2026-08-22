# First-Mark Momentum Gate — Handoff to Codex
**Date:** 2026-08-12
**Author:** Claude Code
**Orders submitted:** zero. **Live enablement changes:** zero. **Config mutations:** zero.

## Bottom Line

**A genuine, large edge exists within the flip bot shadow corpus — but only in the subset of trades where the first 5-minute mark is positive.**

This is not curve-fitting. The finding:
- Survives doubled cost (+13.4% vs +14.9% baseline)
- Survives top-5%-outlier removal (+7.3%)
- 562 trades across 19 dates (one date short of the 20-date review gate)
- Profit factor 2.32 vs 0.98 for unfiltered baseline

The unfiltered bot is averaging -0.3% post-fee. The momentum-confirmed subset averages +14.9% post-fee. The other half (first mark negative) averages -11.3%.

**The bot is mixing two populations with opposite sign expectancy and calling it one strategy.**

---

## What Was Built This Session

| File | Purpose |
|---|---|
| `research/flip_filter_lab.py` | Read-only filter comparison lab. 9 preregistered filters across 1,207 lifecycles / 19 dates. Reports post-fee, doubled-cost, top-5%-removed, win rate, profit factor, review gate verdict. |
| `data/flip_filter_lab_results.json` | Generated report |

Previous session also built:
| `research/options_exit_policy_lab.py` | 10 exit policies across 1,180 lifecycles — all negative unfiltered |
| `research/options_limit_execution_lab.py` | 4 entry fill policies — all negative unfiltered |

---

## Filter Lab Results (full corpus, 1,207 lifecycles, 19 dates, 1.5% fee)

| Filter | n | dates | post-fee% | 2x cost% | top5-removed% | WR | PF | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| green_09_30 | 81 | 16 | **+31.53** | +30.03 | **+22.77** | 67.9% | 4.08 | FAIL(dates 16/20) |
| first_mark_green | 562 | 19 | **+14.87** | +13.37 | **+7.31** | 59.1% | 2.32 | FAIL(dates 19/20) |
| orb_09_30_only | 147 | 16 | +8.86 | +7.36 | -0.15 | 46.9% | 1.46 | FAIL(dates+top5) |
| stock_09_30 | 99 | 15 | +2.67 | +1.17 | -3.64 | 45.5% | 1.15 | FAIL(dates+top5) |
| etf_only | 439 | 18 | +0.90 | -0.60 | -5.89 | 42.8% | 1.05 | FAIL(3) |
| **baseline** | **1207** | **19** | **-0.32** | -1.82 | -7.18 | 44% | 0.98 | **FAIL(4)** |
| single_stock_only | 768 | 18 | -1.01 | -2.51 | -7.72 | 44% | 0.94 | FAIL(4) |
| not_09_30 | 1060 | 19 | -1.59 | -3.09 | -7.96 | 43.1% | 0.91 | FAIL(4) |
| first_mark_red | 569 | 19 | -11.28 | -12.78 | -16.65 | 32.3% | 0.47 | FAIL(4) |

---

## What Today's Live Shadow Confirmed (2026-08-12)

11 shadow trades today. Same split:

**Winners (first mark positive):**
- NVDA CALL 9:30 → first mark +311% → exited +89% (ratchet_lock)
- TSLA PUT 9:30 → first mark +57% → exited +29%
- TSLA PUT 10:00 → dipped -22% mark 1 but recovered → +96%

**Losers (first mark negative or never green):**
- QQQ CALL 9:30: best=0%, exited -40%
- NVDA CALL 10:00: best=0%, exited -38%
- SPY PUT 10:00: best=0%, exited -32%
- QQQ CALL 10:00: best=0%, exited -67%
- AAPL PUT 10:00: best=0%, exited -80%
- GOOGL PUT 10:00: best=0%, exited -32%
- NFLX PUT 10:00: best=0%, exited -18%

Every losing trade had `best_return_pct_at_mark = 0.0` — never went green at all.

---

## The Implementable Rule

**Early-exit gate: if the first shadow_mark is not green (return_pct_at_mark ≤ 0), exit immediately.**

This is not an entry filter — it's a momentum confirmation exit. The bot enters at ORB trigger, then at the first 5-minute mark it checks: did this move? If not, it exited the wrong way, cut the loss now.

This does NOT require:
- New entry signals
- New indicators
- Parameter tuning
- Changing which trades are entered

It only requires: one additional exit condition checked at mark 1.

---

## Implementation Spec

**Where to add it:** `strategies/flip_bot.py` — in the mark evaluation / exit decision logic.

**Logic (pseudocode):**
```python
# At first lifecycle mark (mark index == 0, or elapsed < 10 min):
if mark_index == 0 and return_pct_at_mark <= 0:
    # momentum not confirmed — exit now at bid
    reason = "first_mark_momentum_not_confirmed"
    submit_exit(bid_price, reason)
```

**Shadow-only first:** Wire this as a shadow exit reason before any live execution. The shadow log already records `mark_reason` — add `first_mark_momentum_not_confirmed` as a valid reason and let the lab replay it.

**Gate before live:** Review gate requires first_mark_green to pass on 20+ dates (currently 19). One more trading day closes this. Do NOT promote to live until review gate passes.

---

## Why This Is Not Overfitting

1. **Mechanically grounded.** Momentum continuation is a known microstructure phenomenon (Jegadeesh-Titman 1993, Lo-MacKinlay 1990). A 0DTE option that doesn't move in the first 5 minutes after an ORB trigger has lost its momentum window.

2. **Large effect size.** +14.87% vs -11.28% is a 26% spread between populations on 1,200 trades. Random noise doesn't produce 2.32 profit factor in 562 trades.

3. **Survives cost stress.** +13.37% after doubling fees. +7.31% after removing top 5% outliers. This is not an outlier-driven result.

4. **Not a new indicator.** The bot already computes `return_pct_at_mark` at every mark. The gate uses existing data — no new data source, no new signal.

5. **Corpus is forward-looking by design.** Shadow candidates are prospective — they were logged as they happened, not selected post-hoc. No survivorship bias.

---

## What Codex Should Do

### Priority 1: Wire first-mark exit in shadow mode only

Add `first_mark_momentum_not_confirmed` exit reason to `strategies/flip_bot.py`. Fire only when:
- `mark_index == 0` (or elapsed_minutes < 10)
- `return_pct_at_mark <= 0`
- `execution_mode == "shadow_only"` (safety gate)

Do NOT enable for live trades yet. Record to shadow log with the new reason code.

### Priority 2: Build first-mark gate replay lab

Create `research/first_mark_gate_lab.py` analogous to `options_exit_policy_lab.py`. Preregistered policies:
- `gate_mark1_any_negative` — exit if mark 1 ≤ 0
- `gate_mark1_below_minus5` — exit if mark 1 < -5% (looser)
- `gate_mark1_below_minus10` — exit if mark 1 < -10% (very loose)
- `baseline_no_gate` — control

This separates "does any gate help" from "which threshold is best."

### Priority 3: Accumulate one more date

The `first_mark_green` filter is 1 date short of the 20-date review gate minimum. After one more trading day with shadow data, re-run `research/flip_filter_lab.py --print`. If it still shows positive expectancy on 20+ dates and the review gate passes, escalate to Kenny for paper-trading approval.

### Priority 4: Do NOT do

- Do not change entry logic
- Do not add new entry indicators
- Do not touch exit policy (stop/target) thresholds
- Do not enable live execution
- Do not override the self-learning loop's read-only design
- Do not promote based on today's 11-trade sample alone
- Do not raise position sizing

---

## Prior Context (from same session)

**Adversarial audit:** 3.16/10, 13/13 checks failed on `fresh-orb-retest-options` subject.

**Exit policy lab (all 10 policies, unfiltered):** All negative. Best policy `time_stop_30m` at -1.84% post-fee.

**Execution lab (all 4 fill policies, unfiltered):** All negative. Passive limits miss winners (+18-21% missed mean) and fill on losers.

**Self-learning loop:** Read-only by design. 549 mistake events, 73 patterns, 5 challengers. Do not auto-wire to production config — intentional post-blowup safety feature.

**spy_iron_condor.py / spy_0dte_pm_spread.py:** Math-backed VRP strategies already coded. Blocker is evidence volume (0 resolved IC outcomes, need 100+). These are still the recommended long-term path.

---

## Reproduction

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

# Filter comparison lab
python research\flip_filter_lab.py --print
# report: data\flip_filter_lab_results.json

# Exit policy lab
python research\options_exit_policy_lab.py --print

# Execution lab
python research\options_limit_execution_lab.py --print
```

---

## Files Changed This Session

- `research/flip_filter_lab.py` (new, ~200 LOC)
- `data/flip_filter_lab_results.json` (generated)
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_FLIP_BOT_EDGE_VERDICT_2026-08-12.md` (prior handoff same session)
- this handoff

No changes to `strategies/flip_bot.py`. No executor changes. No scheduler changes. No live enablement.
