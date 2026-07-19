# Claude Code Handoff: Project Skill Library + Adaptive Trading Memory

Date: 2026-07-05
Owner: Codex
Status: Ready for Claude Code implementation

## Why This Exists

User shared screenshots recommending that high-capability models write durable `SKILL.md` / memory files before model access changes. The core idea is correct for this repo: capture the best reasoning, verification habits, market-condition playbooks, failure stories, and operating rules so future Claude/Codex sessions inherit them instead of rediscovering them.

The user's stated objective:

> Build the best autonomous trading bot ever. It must know the ins and outs of every market condition, adapt, learn, execute with precision, and know when to trade and when not to trade.

This handoff asks Claude Code to implement a local project skill/memory library for Vibe-Trading.

## Current Bot Context

Repo:

`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Recently added/changed by Codex:

- `scripts/adaptive_options_shadow_playbook.py`
  - shadow-only adaptive market-condition/playbook selector
  - labels conditions such as bearish trend, mixed chop, market closed, liquidity blocked, thin credit, Flip confirmation
  - chooses playbooks like long put, long call, put credit spread, call credit spread, iron condor, or stand aside
- `scripts/run_adaptive_options_shadow_playbook.ps1`
- `scripts/signal_stack_health_report.py`
  - tracks Adaptive Options health
- `research/signal_registry.json`
  - registered Adaptive Options as shadow-only, cannot submit orders
- `scripts/closed_trade_postmortem.py`
  - now adds structured `pnl_explanation` for every closed trade
- `strategies/iwm_options_bot.py`
  - now records structured skip reasons for put spread skips and handles closed-market pending exits safely
- `scripts/options_liquidity_feasibility.py`
  - handles NaN open interest safely

Latest verification from Codex:

- Focused tests: `47 passed`
- Signal health: `OK=38 STALE=0 MISSING=0 ERROR=0`
- Execution audit: `73 signals`, `0 issues`, `1 warning`
- Adaptive Options remains shadow-only: `execution_enabled=false`, `can_submit_orders=false`

## Implementation Goal

Create a durable project-level skill/memory library that future Claude/Codex sessions can read before modifying the bot stack.

It should encode:

1. how to reason about this trading system,
2. how to verify work before saying done,
3. how to evaluate market conditions and choose playbooks,
4. how to explain every P/L and every skip,
5. how to avoid unsafe execution changes,
6. how to preserve hard-earned failure lessons.

## Suggested Files To Create

Create a new directory:

`project_memory/`

Recommended files:

1. `project_memory/README.md`
   - index of the memory library
   - short instruction: read these before changing trading bots, signal stack, dashboard, or schedulers

2. `project_memory/SKILL.md`
   - top-level Vibe-Trading operating skill
   - include mission, safety hierarchy, verification loop, and decision workflow

3. `project_memory/market_conditions_playbook.md`
   - map market conditions to playbooks
   - bullish trend -> long calls / call debit / put credit spreads
   - bearish trend -> long puts / put debit / call credit spreads
   - range/chop -> iron condor or stand aside
   - vol expansion -> directional debit/event research first
   - vol crush/low premium -> avoid short-premium traps unless credit/risk proves enough
   - market closed/unclear/liquidity blocked -> stand aside

4. `project_memory/bot_failure_stories.md`
   - preserve failure lessons:
     - Flip Bot old 69-contract blowup was config/risk failure, not current strategy failure
     - options monitor previously tried to close during closed market and got Alpaca rejects
     - options liquidity gate crashed on NaN open interest
     - SPY options bot skipped valid Flip SPY wins because its SPY playbook was bullish put spread only
     - weekend/holiday stale false alarms fixed with last-weekday logic

5. `project_memory/verification_checklist.md`
   - exact commands and expectations:
     - `python -m pytest ...`
     - `python scripts\execution_gate_audit.py --print`
     - `python scripts\signal_stack_health_report.py`
     - dashboard generation if touched
     - scheduler checks if runners/tasks touched
   - include rule: do not report done until tests, health, and audit are run or explicitly explain why not

6. `project_memory/trade_explanation_contract.md`
   - every trade must explain:
     - entry thesis
     - market regime
     - selected playbook
     - exit reason
     - P/L source, realized vs estimated
     - primary driver of profit/loss
     - risk lesson
     - next action
   - every skipped trade must explain blockers

7. `project_memory/execution_safety_contract.md`
   - no live/paper execution changes without explicit user approval
   - read-only/shadow-only defaults
   - preserve execution_enabled/can_submit_orders flags
   - never bypass kill switch, max contracts, risk pct, duplicate exposure, market-closed checks

8. `project_memory/claude_code_start_here.md`
   - a short entrypoint for Claude Code sessions:
     - read project_memory first
     - inspect git status
     - avoid reverting user/Codex changes
     - use system Python for tests if uv temp env triggers SAC/numpy issues
     - run health/audit before final

## Optional Alternative

If Claude Code thinks these should be installed as formal Codex skills, create a second copy under a skill-compatible folder after confirming the correct local skill install path. Do not overwrite existing global skills without user approval.

## Content Requirements

The writing should be practical and repo-specific, not generic AI advice.

Use concrete examples from this repo:

- Flip Bot SPY post-fix success vs old risk blowup
- SPY options skip explanation:
  - below 20SMA on 2026-06-18 through 2026-06-29
  - credit/risk below 20% on 2026-06-30 through 2026-07-02
- Adaptive Options behavior:
  - label market condition first
  - choose playbook second
  - stand aside on market closed, unclear tape, liquidity blocked
- Postmortem explanation contract:
  - no trade P/L without a cause
  - no skip without blockers

## Guardrails

Do not change bot execution behavior in this task.
Do not enable orders.
Do not modify risk thresholds.
Do not delete or rewrite existing logs.
Do not revert unrelated dirty worktree changes.

This task is documentation/memory scaffolding only, plus tests if Claude Code adds a loader or validation script.

## Suggested Validation

At minimum:

```powershell
python -m pytest agent/tests/test_account_flip_shadow_scanners.py agent/tests/test_closed_trade_postmortem.py agent/tests/test_iwm_options_confidence_gate.py agent/tests/test_options_liquidity_feasibility.py agent/tests/test_flip_bot_safety.py -q
python scripts\execution_gate_audit.py --print
python scripts\signal_stack_health_report.py
```

If Claude Code creates a validation script for `project_memory/`, add focused tests for:

- all required files exist
- `SKILL.md` references verification, safety, market conditions, and P/L explanation
- execution safety contract contains `execution_enabled=false` and `can_submit_orders=false` language

## Definition Of Done

- `project_memory/` exists with the recommended files or an equivalent well-organized structure.
- The files are specific enough that a future model can continue this project without losing the operating philosophy.
- Safety/audit posture remains unchanged.
- Claude Code reports what it created and what it intentionally did not change.
