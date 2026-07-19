---
name: vibe-trading-options-bot
description: Use when working on IWM/options bot logic, credit spreads, iron condors, liquidity checks, pending exits, or directional adaptation.
---

# Vibe-Trading Options Bot

## File
`strategies/iwm_options_bot.py`

## Active Strategies
- Iron Condor (16-delta, 30-45 DTE) — IWM, TSLA
- Bull Put Spread (25-delta, 7-14 DTE) — IWM, SPY, QQQ, AAPL, NVDA, PLTR
- Wheel (NVDA, AAPL)

## Exit Rules
- Profit target: 50% of credit received
- Stop loss: 100% of credit (full loss)
- `is_option_market_open()` must return True before any close order
- Closed-market exits: set `exit_pending_reason`, retry next session
- Spread recovery clears `exit_pending_reason` (fixed 2026-07-06)

## Options Liquidity Gate (5 criteria, score ≥ 4 = eligible)
Script: `scripts/options_liquidity_feasibility.py`
1. 0DTE available
2. Weekly available (within 7 days)
3. ATM OI ≥ 500
4. Spread ≤ 15% of mid
5. Contract price ≤ $5/share (account-size constraint)

**Important**: META and TSLA fail criterion 5 (expensive contracts for small account). Gate failure ≠ remove from SHADOW_CANDIDATES. Shadow logging continues. Gate only blocks live execution.

## Qualified vs Blocked (as of 2026-07-04)
- Qualified: IWM, NVDA, SPY
- Borderline: QQQ, AAPL, NFLX
- Blocked (price): META, TSLA, RDDT

## Candidate Confidence
`candidate_confidence.score` must be ≥ threshold for execution. Logged per-trade.

## Open Positions (2026-07-06 state)
- IWM iron condor — open
- AAPL put spread — `exit_pending` (past stop, awaiting Monday open)
- PLTR put spread — open

## When Changing Options Bot
1. Run `python -m pytest agent/tests/test_iwm_options_confidence_gate.py -q`
2. Run `python -m pytest agent/tests/test_options_liquidity_feasibility.py -q`
3. Confirm `execution_enabled: False` still in `build_report()` output
4. Never force-close when `is_option_market_open()` is False
