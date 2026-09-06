# Independent review request: governed shadow decision spine

## Scope

Review these changes only:

- `scripts/governed_shadow_decision.py`
- `scripts/governed_shadow_alert.py`
- `scripts/governed_shadow_lifecycle.py`
- `scripts/governed_shadow_outcome.py`
- `scripts/governed_shadow_rule_update.py`
- `scripts/closed_trade_postmortem.py`
- `scripts/flip_bot_learning_report.py`
- `scripts/post_trade_learning_cycle.py`
- `strategies/flip_bot.py`
- `scripts/generate_dashboard.py`
- `scripts/run_intraday_opportunity_radar.ps1`
- `agent/tests/test_governed_shadow_decision.py`
- `agent/tests/test_permanent_learning_loop_guards.py`

## Non-negotiable invariants

1. This is a paper/simulation system: no broker client, HTTP order route, or live execution may be added.
2. Every emitted decision must retain `execution_enabled=false` and `can_submit_orders=false`.
3. LLM/agent output is evidence or criticism only. The deterministic policy is the sole decision authority.
4. Confirmed scanner candidates are visible whether accepted or rejected; a rejection cannot suppress the scanner alert.
5. The append-only decision ledger must be idempotent by completed-bar candidate identity.
6. P/L totals must not merge unreconciled option outcomes with exact ledger P/L.
7. A degraded recent regime pauses *new simulated positions*, but never hides confirmed alerts.
8. Scheduler order must remain candidate → evidence/veto → shadow alert → lifecycle → outcome → rule nomination.
9. Rule updates are nominations only after the frozen sample minimum; no automatic parameter mutation.

## Review questions

- Can an entry bypass `stand_aside` or `needs_review` due to a misleading `allowed=true` field?
- Can refreshes create duplicate decisions or duplicate simulated positions?
- Are current dashboard labels honest about exact, estimated, and unreconciled P/L?
- Do runner ordering and data dependencies preserve an alert before a governed decision is recorded?
- Identify only P0/P1 correctness, safety, or data-integrity defects. Do not redesign the architecture or change risk thresholds.

## Required checks

```powershell
python -m py_compile scripts/governed_shadow_decision.py scripts/governed_shadow_alert.py scripts/governed_shadow_lifecycle.py scripts/governed_shadow_outcome.py scripts/governed_shadow_rule_update.py scripts/closed_trade_postmortem.py scripts/flip_bot_learning_report.py scripts/post_trade_learning_cycle.py scripts/generate_dashboard.py strategies/flip_bot.py
python -m pytest agent/tests/test_governed_shadow_pipeline.py agent/tests/test_governed_shadow_decision.py agent/tests/test_permanent_learning_loop_guards.py agent/tests/test_post_trade_learning_cycle.py agent/tests/test_generate_dashboard.py agent/tests/test_intraday_opportunity_radar.py -q
python scripts/order_authority_invariant.py
git diff --check
```

Return findings with file and line reference. Do not edit any live-execution configuration. If no P0/P1 issues are found, state that explicitly.
