---
name: vibe-trading-safety-gates
description: Use when modifying anything that can affect orders, execution flags, live trading, risk sizing, max contracts, kill switches, or broker APIs.
---

# Vibe-Trading Safety Gates

## Trigger
Any change touching: order submission, `LIVE_EXECUTION_ENABLED`, `MAX_CONTRACTS`, `max_risk_pct`, kill switch files, broker credentials, `.env`, execution gate, or signal promotion.

## Hard Rules (never bypass without explicit user approval)
- `LIVE_EXECUTION_ENABLED` defaults `false` via env var. Never set it true in code.
- `MAX_CONTRACTS = 5` in `strategies/flip_bot.py:90`. Do not raise.
- `max_risk_pct = 0.02` (2%). The old 25% caused a 69-contract blowup on 2026-06-23.
- Kill switch files live at `~/.vibe-trading/MANUAL_RESET_REQUIRED.json` and `~/.vibe-trading/PORTFOLIO_KILL_SWITCH.json`. Never delete or mock these.
- `/v2/orders` must never appear in any new script or dashboard file.
- No social/X/PMXT/prediction-market context wires directly to orders.
- No scanner promotes to execution gate without entry in `rules/signal_promotion_rules.md`.

## Pre-Change Checklist
1. `python scripts/execution_gate_audit.py --print` — must pass, 0 issues.
2. Grep new file for `/v2/orders`, `LIVE_EXECUTION_ENABLED = True`, `place_order`, `submit_order`.
3. Confirm `execution_enabled: false` in any new report output.
4. Run affected test file: `python -m pytest agent/tests/<test_file>.py -q`.

## Post-Change Verification
```powershell
python scripts/execution_gate_audit.py --print
# Expected: passed=True signals=73+ issues=0
```

## Red Flags
- Any script that imports `alpaca.trading.client.TradingClient` and calls `.submit_order`.
- A `build_report()` that returns `execution_enabled: True` without an explicit user decision.
- Changing risk pct via a constant rather than env var.
- A new `.ps1` runner that calls the bot without `--dry-run` or read-only flag.
