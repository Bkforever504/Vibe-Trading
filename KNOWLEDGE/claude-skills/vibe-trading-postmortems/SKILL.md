---
name: vibe-trading-postmortems
description: Use when generating closed trade postmortems, daily outcome reviews, missed banger reviews, needs-review queues, or per-trade P/L explanations.
---

# Vibe-Trading Postmortems

## Scripts
| Script | Output | Purpose |
|---|---|---|
| `scripts/closed_trade_postmortem.py` | `data/closed_trade_postmortem_log.jsonl` | Per-trade: why it won/lost, giveback %, capture efficiency |
| `scripts/daily_outcome_review.py` | `data/daily_outcome_review_log.jsonl` | Daily roll-up of all trade outcomes |
| `scripts/missed_banger_review.py` | `data/missed_banger_review_log.jsonl` | Symbols that moved 5%+ but bot didn't trade |
| `scripts/flip_shadow_pnl_evaluator.py` | `data/flip_shadow_pnl_evaluation_log.jsonl` | Simulated exits, giveback, ratchet comparison |

## Capture Efficiency Metric
```
capture_efficiency = realized_pnl_pct / best_pnl_pct
```
July 6 average: **0.417** (only 41.7% of peak profit captured). Target > 0.70.

## Missed Banger Classification
`_classify_miss()` returns one of:
- `not_a_banger` — move < 5%
- `bot_covered` — bot saw setup and traded
- `universe_gap` — symbol not in deep scan
- `liquidity_gate_blocked` — in universe, failed options liquidity
- `setup_not_triggered` — qualified but no flip shadow signal

## Postmortem Fields to Check
- `giveback_pct` — how much peak profit was surrendered
- `capture_efficiency` — realized / peak
- `missed_target_distance_pct` — how far from profit target at exit
- `ratchet_would_have_helped` — bool, simulated ratchet outcome

## When Adding a New Postmortem Field
1. Add to `closed_trade_postmortem.py` output dict
2. Add test in `agent/tests/test_closed_trade_postmortem.py`
3. Surface in dashboard `render_daily_pnl()` if user-visible

## Red Flags
- Postmortem that blames exit logic when the real failure was entry/regime
- Missed banger report not cross-referencing deep scan universe (survivorship bias)
- `giveback_pct` computed from entry price, not from peak (wrong denominator)
