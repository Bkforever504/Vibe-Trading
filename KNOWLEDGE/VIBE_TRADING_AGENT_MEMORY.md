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
# → OK=61+ STALE=0 MISSING=0 ERROR=0

python scripts/execution_gate_audit.py --print
# → passed=True signals=102+ issues=0

python -m pytest agent/tests/ -q --tb=no
# → 4461 passed, 0 failed, 4 skipped  ← FULL SUITE, not just 2 files

python scripts/generate_dashboard.py
# → Wrote ~/.vibe-trading/dashboard.html
```

## CLAUDE SELF-CORRECTION RULES (added 2026-08-08 — Codex caught these misses)
- ALWAYS run full test suite `agent/tests/` not partial. Never report "tests pass" from 2 files.
- ALWAYS verify day-of-week for any date written (Aug 10=Mon, Aug 11=Tue).
- ALWAYS use `_now_et().date()` not `date.today()` for market date — timezone bug.
- ALWAYS check ALL scheduled task settings: overlap (MultipleInstances), time limit, battery, wake.
- ALWAYS check telemetry event names against supported schema before using.

## Known Pre-existing Test Failures (not our bugs)
7 futu/mootdx Chinese market loader tests fail in full suite due to test-order pollution. Pass in isolation. Ignore for bot-scope reporting.

## Current Bot State (2026-08-08)
- Flip Bot: 14 closed trades total, 0 open. P&L all-time: -$9,245.50 (includes 69-contract blowup pre-fix)
- Post-hardening (after 2026-06-29): 13 trades, +$2,312, 61.5% win rate, 4.78 profit factor
- Symbols: SPY + QQQ only. $1k account override. Paper only. Live execution disabled.
- Signal health: OK=61 STALE=0 ERROR=0
- Execution gate: 102 signals, 0 issues
- Scheduler: 4 flip tasks hardened (20-min limit, IgnoreNew, wake, battery tolerance) — commit 677bf08
- Monday Aug 10: first clean execution attempt after 3 bug fixes

## Flip Bot Critical Variable Facts (2026-08-08)
- Spot price in `_find_0dte_for_symbol` = `price` (from `price = _spot(sym)` ~line 2117). NEVER use variable `spot`.
- VIX keys: `regime`="backwardation"/"contango"/"flat", `vix_over_vix3m` (>1.0=stress), `vix3m_over_vix` (>1.0=calm).
- Hard blocks: ONLY `portfolio_kill_switch_active`. `options_liquidity_blocked` is advisory (demoted 2026-08-08).
- Shadow gate: advisory for SPY/QQQ. `stand_aside` → size down, NOT block. `allowed=True` for both.
- Telemetry: use `"exit"` not `"exit_fill"` — exit_fill is unsupported.

## Architecture in One Sentence
Flip Bot + Options Bot trade paper Alpaca. 38 shadow scanners gather evidence. Adaptive playbook labels conditions. Debate layer produces verdicts. Execution gate audits everything. Dashboard shows it all read-only.
