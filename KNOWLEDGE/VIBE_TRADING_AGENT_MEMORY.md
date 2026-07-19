# Vibe-Trading Agent Memory
Last updated: 2026-07-06

## Safety Rules (never bypass)
- `LIVE_EXECUTION_ENABLED = false` always (env-var controlled, default false)
- `MAX_CONTRACTS = 5` hard ceiling — the 69-contract blowup happened at 25% risk with no cap
- `max_risk_pct = 0.02` (2%) — was 25%, caused -$11,557 loss on 2026-06-23
- Kill switches: `~/.vibe-trading/MANUAL_RESET_REQUIRED.json`, `PORTFOLIO_KILL_SWITCH.json` — never delete
- No `/v2/orders` in dashboards, scanners, or reports
- No social/prediction-market signal wires directly to orders
- No scanner promotes to execution without entry in `rules/signal_promotion_rules.md`

## What Not to Touch Without Explicit Approval
- `LIVE_EXECUTION_ENABLED`, `MAX_CONTRACTS`, `max_risk_pct`, kill switch files
- `.env` or broker credentials
- Execution gate audit passing status (must stay passed=True issues=0)
- Any script that submits Alpaca orders

## Failure Memory
| Date | Event | Fix |
|---|---|---|
| 2026-06-23 | 69-contract SPY blowup, -$11,557 | risk→2%, MAX_CONTRACTS=5 |
| 2026-07-06 | SPY call peaked +66%, exited +17% | ratchet: arm@40%, giveback=15pts |
| 2026-07-06 | Second SPY call chase loss -$242 | same-day re-entry block added |
| pre-2026-07-06 | AAPL options reject loop | market-open check before close orders |

## How to Interpret Flip Bot Grade
- All-time grade: **F** (dominated by 69-contract pre-fix blowup)
- Post-fix grade (after 2026-06-26): **B**, 7/7 wins, +$2,855 P&L
- Always show both when evaluating Flip Bot performance
- `config_change_date: "2026-06-26"` in signal_registry.json marks the split

## How to Verify Stack Before Saying Done
```powershell
python scripts/signal_stack_health_report.py --no-write
# → OK=38+ STALE=0 MISSING=0 ERROR=0

python scripts/execution_gate_audit.py --print
# → passed=True signals=73+ issues=0

python -m pytest agent/tests/test_flip_bot_safety.py agent/tests/test_iwm_options_confidence_gate.py -q
# → all pass (use system Python, not uv+numpy)

python scripts/generate_dashboard.py
# → Wrote ~/.vibe-trading/dashboard.html
```

## Known Pre-existing Test Failures (not our bugs)
7 futu/mootdx Chinese market loader tests fail in full suite due to test-order pollution. Pass in isolation. Ignore for bot-scope reporting.

## Current Bot State (2026-07-06)
- Flip Bot: 8 closed SPY trades, 0 open, ratchet now active
- Options Bot: AAPL put spread exit_pending (Monday), IWM condor open, PLTR spread open
- Signal health: OK=38 STALE=0 ERROR=0
- Execution gate: 73 signals, 0 issues
- Dashboard: `~/.vibe-trading/dashboard.html`

## Architecture in One Sentence
Flip Bot + Options Bot trade paper Alpaca. 38 shadow scanners gather evidence. Adaptive playbook labels conditions. Debate layer produces verdicts. Execution gate audits everything. Dashboard shows it all read-only.
