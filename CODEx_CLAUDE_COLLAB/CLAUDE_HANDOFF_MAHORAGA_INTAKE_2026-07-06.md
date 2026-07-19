# Claude Code Handoff - MAHORAGA Intake

Date: 2026-07-06
Generated: 2026-07-07T03:59:10.732002Z

## Objective

Evaluate MAHORAGA-inspired architecture improvements without importing external code, deploying Workers, or touching broker execution.

## Next Task

- ID: evaluate-mahoraga-staleness-exit
- Title: Evaluate social/momentum staleness as a Flip Bot shadow exit lesson
- Instructions: Build only if it remains read-only and compares social heat decay against Flip Bot postmortems and capture gaps.

## Top Local Upgrade Queue

- staleness_exit_shadow: convert_to_read_only_tool -> flip_social_staleness_shadow (confidence=90, risk=10)
- pluggable_strategy_contract: adopt_design_pattern -> strategy_module_contract_doc (confidence=88, risk=8)
- dashboard_status_logs_api: extend_existing_tool -> dashboard_loop_state_panel (confidence=78, risk=12)
- social_sentiment_gatherers: extend_existing_tool -> extend_public_social_intake_schema (confidence=82, risk=18)
- policy_wrapped_execution_design: study_only -> execution_policy_contract_review (confidence=74, risk=22)
- cloudflare_durable_state: study_only -> state_backend_tradeoff_note (confidence=55, risk=35)

## Hard Blocks

- Do not deploy MAHORAGA.
- Do not copy Alpaca execution endpoints.
- Do not route social sentiment directly to orders.
- Do not adopt 25pct cash sizing.

## Commands

```powershell
python scripts\mahoraga_repo_intake_audit.py --print
python scripts\execution_gate_audit.py --fail-on-issues --print
python -m pytest agent\tests\test_mahoraga_repo_intake_audit.py -q
```
