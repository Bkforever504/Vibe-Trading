# Claude Code Handoff: Flip Gate-Stack Regression

**Date:** 2026-07-15 CT  
**Repository:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`  
**Primary bot files:**

- `strategies\flip_bot.py`
- `strategies\shadow_consensus.py`
- `scripts\shadow_consensus_gate.py`
- `scripts\shadow_consensus_blocker_audit.py`

## Objective

Preserve the Flip Bot's account protections while correcting an over-filtering regression caused by research/advisory models acquiring hard execution-veto authority.

The user observed that results seemed to worsen as more improvement modules were added. The evidence supports a narrower conclusion:

- Executed trade quality has not been proven to deteriorate.
- Opportunity flow materially deteriorated.
- Correlated and setup-agnostic alpha opinions were suppressing otherwise-qualified Flip setups.

## Verified Performance State

Latest post-hardening Flip sample:

- Closed trades: 10
- Net P&L: `$2,538`
- Win rate: `80.0%`
- Profit factor: `7.59`
- Expectancy: `$253.80/trade`
- Maximum/current drawdown: `-$385 (-13.2%)`
- No new Flip closure since 2026-07-07

This is encouraging but statistically small. The feature-ablation report has zero legacy trades with sufficient feature telemetry, so no causal claim can be made that newer indicators improved or harmed executed trade quality.

## Root Cause

`scripts\shadow_consensus_gate.py` calls itself a read-only advisor and emits:

- `execution_enabled: false`
- `can_submit_orders: false`
- recommendations such as `approve`, `size_down`, `needs_review`, and `stand_aside`

However, `strategies\shadow_consensus.py::entry_advice()` converted broad alpha opinions into hard Flip entry vetoes. `strategies\flip_bot.py` then skipped the candidate whenever `allowed` was false.

Observed evidence from `C:\Users\kenne\.vibe-trading\logs\flip-decisions.jsonl`:

- `42` candidates were blocked by `shadow_consensus_block`.
- The latest bearish SPY PUT setups were blocked by a static symbol-level verdict containing:
  - `adaptive_flip_evidence_does_not_confirm_bullish_direction`
  - `adaptive_put_credit_spread_credit/risk_is_below_minimum`
  - `adaptive_stand_aside`
  - `market_force_unclear`
  - `weak_shadow_pnl_evidence`
  - catalyst and Kronos cautions

This verdict was not aware that the requested setup was a long PUT. A bullish-direction objection and a put-credit-spread constraint therefore vetoed a bearish long-option trade even though those checks represented different strategies.

The current SPY shadow evidence was positive but immature:

- Completed lifecycles: 8
- OOS expectancy: `+7.09%`
- Win rate: `37.5%`
- Payoff ratio: `2.208`
- Promotion eligible: false, correctly, because the formal requirement remains 100 completed / 30 OOS / 10 trading days

## Repair Applied

### 1. Restore the advisory authority boundary

Changed `strategies\shadow_consensus.py::entry_advice()`.

Only these consensus facts retain hard-block authority:

- `portfolio_kill_switch_active`
- `options_liquidity_blocked`

The portfolio kill switch also remains authoritative through the report-level active flag.

The following are now alpha advice, not hard vetoes:

- `stand_aside` recommendation by itself
- `market_force_unclear`
- `weak_shadow_pnl_evidence`
- Kronos confidence/direction opinions
- adaptive playbook opinions
- candlestick and higher-timeframe opinions
- catalyst caution

For `stand_aside`, `needs_review`, or `size_down`, requested contracts are conservatively halved, never increased. Example: five contracts become two. For a true safety blocker, contracts become zero.

New return telemetry:

- `hard_blockers`
- `alpha_advisory_only`

### 2. Persist authority telemetry in Flip decisions/trades

Changed `strategies\flip_bot.py` to record:

- `hard_blockers`
- `alpha_advisory_only`

These fields are included in blocked decision attribution and the stored `shadow_consensus` entry context.

### 3. Correct historical blocker attribution

Changed `scripts\shadow_consensus_blocker_audit.py`.

The old audit compared historical `not_enough_shadow_samples` decisions with today's later completed count and labeled them contradictions. It now distinguishes:

- `current_blocker_seen_despite_symbol_completed_count_meeting_gate_minimum`
- `historical_sample_blocker_now_resolved_by_later_evidence`

Latest regenerated audit:

- Blocker types: 22
- Current sample-count contradictions: 0
- Historical sample blockers later resolved: 38

## Corrected Replay

Read-only replay against the current SPY consensus report:

```text
enabled=true
allowed=true
requested_contracts=5
adjusted_contracts=2
recommendation=stand_aside
hard_blockers=[]
alpha_advisory_only=true
```

Before the repair, the same current verdict produced `allowed=false` and zero contracts.

## Safety Invariants

Do not weaken any of these in follow-up work:

- Portfolio kill switch
- Daily realized-loss guard
- Options liquidity hard failure
- Execution guard confidence requirements
- Maximum notional / contract limits
- Maximum open positions
- Same-day re-entry protection
- Quote freshness and spread checks
- Position reconciliation / fail-closed integrity
- `execution_enabled=False` and `can_submit_orders=False` on research reports
- Formal promotion requirements for shadow challengers

No profit target, stop threshold, daily loss threshold, kill-switch behavior, or live-symbol allowlist was changed in this repair.

Note that the inspected decision rows had `paper: true`. Do not describe them as live broker fills without separately proving the process execution mode and broker order status.

## Verification Completed

Targeted and combined regression suites:

```text
52 passed in 20.15s
```

Covered:

- shadow consensus advisor
- shadow consensus report generation
- shadow consensus exit advice
- blocker audit
- Flip Bot safety
- Flip decision logging
- Flip execution guard
- Flip script execution

Compilation:

```text
python -m py_compile strategies\shadow_consensus.py strategies\flip_bot.py scripts\shadow_consensus_blocker_audit.py
# clean
```

Execution gate audit:

```text
passed=true
issue_count=0
```

Signal-stack health:

```text
OK=58
STALE=0
MISSING=0
ERROR=0
```

## Exact Recheck Commands

Run from the repository root:

```powershell
Set-Location 'C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading'

python -m pytest agent\tests\test_shadow_consensus_blocker_audit.py agent\tests\test_shadow_consensus_advisor.py agent\tests\test_shadow_consensus_gate.py agent\tests\test_shadow_consensus_exit_advice.py agent\tests\test_flip_bot_safety.py agent\tests\test_flip_decision_log.py test_flip_bot_execution_guard.py test_flip_bot_script_execution.py -q

python -m py_compile strategies\shadow_consensus.py strategies\flip_bot.py scripts\shadow_consensus_blocker_audit.py

python scripts\execution_gate_audit.py
python scripts\signal_stack_health_report.py --no-write
python scripts\shadow_consensus_blocker_audit.py --print

python -c "from strategies.shadow_consensus import entry_advice; import json; print(json.dumps(entry_advice('SPY', 5, enabled=True), indent=2))"
```

## Claude Code Next Queue

### 1. Verify the next eligible Flip setup end to end

Confirm that a setup with only alpha caution:

- is not logged as `shadow_consensus_block`
- is reduced in size when requested contracts exceed one
- records `alpha_advisory_only=true`
- still passes every native execution guard before any order path

Confirm separately that a synthetic or fixture-based `options_liquidity_blocked` and active kill switch still yield zero contracts.

### 2. Make consensus setup-aware before granting it any future authority

The current consensus row is symbol-level. It must not regain directional veto power until its interface includes and validates at least:

- requested right (`CALL` / `PUT`)
- setup strategy (`0dte`, `bull_trend`, `bear_trend`, etc.)
- requested structure (long option versus credit/debit spread)
- point-in-time report timestamp/freshness

Do this first in shadow telemetry. Do not promote directional consensus back to a hard gate based on opinion.

### 3. Measure marginal gate value

Build or extend a read-only, timestamp-aligned counterfactual report that attributes each alpha blocker against subsequent executable bid/ask paths. Required outputs per blocker:

- candidates observed
- forward winners/losses
- expectancy
- avoided-loss value
- missed-gain value
- net marginal value
- confidence interval or bootstrap uncertainty
- chronology and data provenance

Correlated blockers must be evaluated jointly, not credited independently for blocking the same trade.

### 4. Preserve exit-evidence work

Continue collecting uncensored post-75% shadow paths. Do not change live exit policy until forward paths can distinguish:

- all-out at +75%
- partial profit plus runner
- no fixed target with ratchet

The present historical comparison was censored because old shadow lifecycles ended at +75%.

## Stop Conditions

Stop and report rather than modifying execution if:

- current broker positions do not reconcile
- kill-switch state is ambiguous
- report timestamps are stale at entry time
- a proposed change increases size
- a proposed gate relaxation lacks point-in-time counterfactual evidence
- local files changed by another agent conflict with these edits

## Worktree Warning

The repository is heavily dirty with user/agent work across many tracked and untracked files. Do not reset, clean, checkout, or revert unrelated changes. Read current files before editing and keep follow-up changes tightly scoped.

## Bottom Line

The user's intuition identified a real systems problem: more research modules had created more independent vetoes, not proven incremental edge. This repair keeps the research stack useful for sizing and learning while restoring the correct hierarchy:

1. Account and execution safety may veto.
2. Native setup logic determines candidate quality.
3. Unproven research opinions advise, size down, and collect evidence.
4. Only preregistered, point-in-time outcome evidence can earn greater authority.
