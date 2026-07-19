---
name: vibe-trading-claude-codex-handoff
description: Use when writing handoffs between Claude Code and Codex, summarizing session state, or making the next session pick up cleanly.
---

# Vibe-Trading Claude/Codex Handoff

## Handoff File Location
`CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_<TOPIC>_<DATE>.md`
`CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_<TOPIC>_<DATE>.md`

## Required Fields in Every Handoff
1. Date and session summary (1 paragraph)
2. Files changed (with line numbers for key changes)
3. Verification results: tests passed, health OK counts, gate audit status
4. Open positions / active risks (especially options pending exits)
5. Next session's priority action
6. Known caveats or deferred items

## End-of-Session Verification Checklist
Run all before declaring done:
```powershell
python scripts/signal_stack_health_report.py --no-write
# → OK=38+ STALE=0 MISSING=0 ERROR=0

python scripts/execution_gate_audit.py --print
# → passed=True issues=0

python -m pytest agent/tests/test_flip_bot_safety.py agent/tests/test_iwm_options_confidence_gate.py agent/tests/test_options_liquidity_feasibility.py agent/tests/test_generate_dashboard.py -q
# → all pass

python scripts/generate_dashboard.py
# → Wrote ~/.vibe-trading/dashboard.html
```

## Claude Code → Codex Handoff Pattern
- Provide exact file paths + line numbers for changes made
- List tests added and their assertions
- Flag any deferred tasks with reason
- Note any safety-relevant decisions explicitly

## Codex → Claude Code Handoff Pattern
- Paste verification output (tests passed, health OK, gate passed)
- List touched files
- Flag any open positions or pending actions
- Include "Important note for Monday" style operational notes

## Session Memory
Full session memory is in `KNOWLEDGE/VIBE_TRADING_AGENT_MEMORY.md`.
Read it at the start of any new session before touching bot code.

## Red Flags
- Handoff that says "tests pass" without showing count
- Handoff that omits open positions
- New session that changes execution flags without reading memory file first
