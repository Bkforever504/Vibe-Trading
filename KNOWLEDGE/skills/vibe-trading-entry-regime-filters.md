---
name: vibe-trading-entry-regime-filters
description: Use when changing entry logic, same-day re-entry rules, trend filters, VWAP/EMA, ORB, TTM squeeze, market force, breadth, HMM, PCA, RV/IV, or regime gates.
---

# Vibe-Trading Entry & Regime Filters

## Flip Bot Entry Stack
File: `strategies/flip_bot.py`
Layers applied before any order:
1. Market hours check (9:30–16:00 ET weekdays)
2. VIX term-structure direction check blocks bull entries in backwardation.
3. Leader breadth requires at least 2 of SPY/QQQ/IWM to meet the trend score.
4. SPY must meet `BEAR_TREND_MIN_CONFIDENCE` for the selected trend direction.
5. ORB and TTM squeeze are confirmation/context layers.
6. Same-day same-symbol same-direction re-entry is blocked unless the new setup is materially stronger.
7. Execution guard checks live flag, confidence, notional, contract cap, spread width, and open-symbol exposure.

## SHADOW_CANDIDATES
```python
SHADOW_CANDIDATES = ["QQQ", "IWM", "NVDA", "TSLA", "AAPL", "META"]
```
These are evidence-gathering only. Promotion to live requires 30 trading days + 10 shadow samples.

## Same-Day Re-Entry Rule (added 2026-07-06)
**Problem**: Second SPY call loss on July 6 was a chase entry after the first trade closed profitably.
**Rule**: Block same-direction re-entry on same symbol same day unless:
- Confidence is 10/10, AND
- Fresh TTM squeeze release + rising momentum (bull), OR
- Bearish ORB confirmation (bear)

## Regime Intelligence Signals (shadow-only, read from logs)
| Signal | Log file | Use |
|---|---|---|
| HMM Regime | `data/hmm_regime_log.jsonl` | panic/chop/trend state |
| PCA Market Forces | `data/pca_market_forces_log.jsonl` | force regime unavailable/bearish/bullish |
| RV/IV Regime | `data/rv_iv_regime_log.jsonl` | volatility expansion/compression |
| Market Force Score | `data/market_force_score_log.jsonl` | score + confidence |
| Opening Range Breadth | `data/opening_range_breadth_log.jsonl` | bullish/bearish/mixed breadth |
| Adaptive Playbook | `data/adaptive_options_shadow_playbook_log.jsonl` | stand_aside or playbook label |

## Key Rule: Regime Signals → Context Only
None of these signals wire directly to orders. They inform the `agent_trade_debate_report.py` which outputs a `final_verdict`. Only `bull_case_leads_execute` or equivalent unlocks execution.

## When Changing Entry Logic
1. Add test to `agent/tests/test_flip_bot_safety.py`.
2. If adding a new regime filter, add to `research/signal_registry.json` first.
3. Run `python scripts/execution_gate_audit.py --print` after.
4. Shadow-test for 30 days before considering execution wiring.

## Red Flags
- Bypassing the confidence gate for "just this one" scenario.
- Wiring a social/prediction-market signal directly to an entry.
- Same-day re-entry without material setup improvement.
