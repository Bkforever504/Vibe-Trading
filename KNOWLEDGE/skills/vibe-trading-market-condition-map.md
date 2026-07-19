---
name: vibe-trading-market-condition-map
description: Use when building adaptive market intelligence: trend, chop, volatility, GEX, VWAP, expected move, dealer hedging, or bias zones.
---

# Vibe-Trading Market Condition Map

## Condition Labels (Adaptive Playbook)
`scripts/adaptive_options_shadow_playbook.py`
Labels applied before any playbook decision:
- `bearish_trend` / `bullish_trend` / `mixed_chop`
- `bearish_opening_range` / `bullish_opening_range`
- `volatility_expansion` / `volatility_compression` / `volatility_unknown`
- `liquid_options` / `options_liquidity_blocked` / `thin_credit`
- `flip_bearish_confirmed` / `flip_bullish_confirmed` / `flip_direction_unknown`
- `market_closed_context`

## Hard Overrides (stand_aside)
- Market closed → stand_aside regardless of other conditions
- Options liquidity blocked → stand_aside

## Intelligence Sources (read-only logs)
| Log | Condition it informs |
|---|---|
| `market_force_score_log.jsonl` | trend direction, score, confidence |
| `opening_range_breadth_log.jsonl` | breadth bias, ORB state |
| `rv_iv_regime_log.jsonl` | volatility expansion/compression |
| `options_liquidity_feasibility_log.jsonl` | liquid_options vs blocked |
| `flip_shadow_pnl_evaluation_log.jsonl` | recent flip direction/win rate |

## Research Queue: Bias Zone + Expected Move
Status: **read-only intake only — not yet implemented**

**Bias Zone (ES/NQ adapted to SPY/QQQ/IWM)**:
- Daily regime label: bullish / bearish / neutral
- Inputs: gamma data, dealer hedging flip zones, VWAP, point of control
- Implementation path: read-only scanner → 30-day shadow → review → possible execution context

**Expected Move Scanner**:
- Daily expected move from options chain (1 std dev)
- Session levels (premarket high/low, prior close, pivot)
- Integration path: context label for entry size / strike selection, not a trade trigger

## Implementation Rules for New Market Intelligence
1. Build as read-only scanner first
2. Log to `data/<name>_log.jsonl`
3. Expose as condition label in adaptive playbook
4. Never wire directly to orders — always through debate/verdict layer
5. 30-day shadow before any execution discussion

## Red Flags
- Bias zone or expected move wired directly to `place_order()`
- Market condition label used as sole entry trigger without confirmation
- GEX data from unverified source used in live execution context
