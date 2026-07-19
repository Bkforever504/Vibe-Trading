---
name: vibe-trading-signal-governance
description: Use when adding signals to signal_registry.json, running execution audits, reviewing signal grades, or applying promotion gates.
---

# Vibe-Trading Signal Governance

## Registry
`research/signal_registry.json`
Current count: 73 signals. Version: 2026-07-06.

## Signal Entry Required Fields
```json
{
  "id": "kebab-case-unique-id",
  "name": "Human Name",
  "type": "shadow|execution|gate|context",
  "execution_enabled": false,
  "source": "script path or description",
  "added_date": "YYYY-MM-DD",
  "notes": "one-line purpose"
}
```

## Execution Audit
```powershell
python scripts/execution_gate_audit.py --print
# Must return: passed=True issues=0
# Acceptable: warnings=1 (broker-client in portfolio concentration monitor)
```
Run after every registry edit or new script addition.

## Signal Grade Tiers
| Grade | Meaning |
|---|---|
| A | Ops-ready, strong evidence |
| B | Good ops, some evidence gaps |
| C | Early evidence, not promotion-ready |
| F | All-time grade dragged by pre-fix artifact |

**Important**: Flip Bot all-time grade is F due to the 69-contract blowup (2026-06-23). Post-fix grade is B (7/7 wins pre-ratchet, 100% WR). Always report post-fix stats alongside all-time when evaluating Flip Bot.

## Promotion Rules
File: `rules/signal_promotion_rules.md`
No scanner can wire to execution without an entry in this file.
Minimum bar: 30 trading days + 10 shadow samples for the symbol.

## config_change_date Convention
When a bot has a major config change, add to registry entry:
```json
"config_change_date": "2026-06-26",
"config_change_note": "risk fixed from 25% to 2%, contracts capped at 5"
```
This allows post-fix performance to be split from all-time in grade reports.

## Red Flags
- New signal added to registry with `execution_enabled: true`
- Signal count drops without explanation
- Grade report showing F for Flip Bot without noting the pre-fix split
- Audit showing issues > 0
