# Claude Code Handoff - Agent Incentive Safety

Date: 2026-07-06
Generated: 2026-07-07T04:21:12.260733Z

## Objective

Turn the Agents of Chaos lesson into practical Vibe-Trading governance: every autonomous or execution-capable loop needs explicit objectives, non-goals, forbidden actions, stop conditions, evidence standards, and independent review.

## Current State

- Passed: True
- Components: 81
- Issues: 82
- High risk: 0
- Medium risk: 0
- Execution capable: 2

## Next Task

- ID: review-agent-incentives
- Title: Add missing incentive controls to high-risk loops before promotion
- Instructions: Patch registry metadata first. Do not change broker wiring, risk thresholds, or execution flags.

## Required Policy Fields

- objective
- non_goals
- forbidden_actions
- escalation_triggers
- evidence_standard
- max_autonomy_level
- verifier_owner

## Promotion Blockers

- None at high-risk level.

## Commands

```powershell
python scripts\agent_incentive_safety_audit.py --print
python scripts\nightly_alpha_factory.py --print
python scripts\execution_gate_audit.py --fail-on-issues --print
python -m pytest agent\tests\test_agent_incentive_safety_audit.py agent\tests\test_nightly_alpha_factory.py -q
```
