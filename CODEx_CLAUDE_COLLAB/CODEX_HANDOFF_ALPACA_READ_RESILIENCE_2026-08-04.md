# Codex to Claude Code Handoff: Alpaca Read Resilience

Date: 2026-08-04

## Objective

Stop transient Alpaca failures from killing monitors, prevent unknown broker
state from being interpreted as flat/empty state, preserve shadow data
collection during broker outages, and keep strategy-specific evidence from
cross-contaminating long-premium decisions.

## Observed Failure

- `iwm_options_bot` crashed on `get_all_positions()` read timeouts because the
  alpaca-py session had `read timeout=None`.
- Flip account sizing silently used `$5,000` when broker equity was unavailable.
- Flip broker-position lookup returned an empty set on failure, which could
  make unknown broker exposure look flat.
- Consensus rows can contain warnings for multiple payoff shapes. A long call
  or put should retain liquidity/portfolio/regime blockers but should not
  inherit credit-to-risk or short-premium-specific warnings.

## Changes

### `scripts/alpaca_resilience.py`

- New read-only resilience module.
- Explicit `(3.05s connect, 12s read)` SDK timeout.
- GET/HEAD/OPTIONS-only transport retry policy for 429/5xx/connect/read errors.
- Application-level bounded read retries with exponential backoff.
- Durable JSONL health events for recovered and exhausted reads.
- No POST/PATCH/DELETE helper. Order submission does not receive automatic
  retries, avoiding duplicate-order risk after ambiguous responses.

### `strategies/iwm_options_bot.py`

- Trading and option-data SDK clients receive explicit timeout/retry policy.
- Account, positions, and daily-order-count reads use `_broker_read()`.
- Monitor position failure leaves state unchanged, alerts, returns `False`, and
  blocks entries instead of crashing or treating the account as flat.
- Unknown per-underlying exposure reaches the exposure cap and blocks stacking.

### `strategies/flip_bot.py`

- Alpaca REST GETs use bounded retries and durable health telemetry.
- Unknown broker positions return `None`; the entry run stops before execution.
- Execution sizing raises when equity is unresolved instead of inventing a
  `$5,000` balance.
- Monitor-side shadow collection may continue with the existing explicitly
  labeled simulated `$5,000` research balance.
- Main no longer fetches account equity for monitor/status/close-only commands.
- Entry advice declares the requested directional playbook.

### `strategies/shadow_consensus.py`

- Added requested-playbook scoping.
- Directional long premium ignores only short-premium-specific blockers:
  credit/risk, IV-not-overpriced, and new-short-premium restrictions.
- Portfolio kill switch, liquidity, regime, catalyst, and other applicable
  blockers remain intact.
- Output records raw blockers and ignored wrong-playbook blockers for audit.

## Verification

- Focused regression: `151 passed`.
- Full suite: `4438 passed, 4 skipped, 4 warnings` in 226.94 seconds.
- Read-only live Alpaca probe:
  - paper account active
  - zero positions
  - 438 ms total account-plus-positions read
  - `execution_enabled=false`
  - `can_submit_orders=false`
- No order endpoint was called and no orders were submitted.

## Profitability Status

This fixes operational integrity and evidence quality. It does not prove an
alpha edge or guarantee a winning trade. The existing ORB continuation shadow
lane remains the strongest directional research cohort, but promotion stays
evidence-gated. Do not loosen portfolio, reconciliation, liquidity, or loss
controls to manufacture activity.

## Worktree Warning

The repository already contains extensive user/generated modifications and
untracked files, including prior work in the same strategy files. No commit was
created because a blind commit would mix unrelated work. Review and stage only
the files listed above plus:

- `agent/tests/test_alpaca_resilience.py`
- `agent/tests/test_shadow_consensus_playbook_scope.py`

## Claude Review Prompt

Review the Alpaca resilience changes for duplicate-order risk, retry storms,
unknown-state handling, and state mutation on read failure. Confirm that retry
behavior applies only to idempotent reads, that monitors preserve state when
positions are unresolved, and that long-premium blocker filtering cannot remove
portfolio kill switches or liquidity hard blocks. Run the focused tests and the
full `agent/tests` suite. Do not submit orders and do not change profitability
gates without forward evidence.
