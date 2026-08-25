# Codex Status — MNQ SMT/CISD Shadow Family

Status: complete and scheduled for shadow-only operation
Date: 2026-08-24

## Delivered

- Four validated frozen candidates in family `mnq-smt-cisd-family`:
  `mnq-smt-cisd-fvg-v1`, `mnq-pdl-rejection-v1`, `mnq-smt-only-v1`, and
  `mnq-cisd-only-v1`.
- Immutable four-symbol universe (MNQ, NQ, MES, ES) with verified membership
  hash.
- Shared deterministic completed-bar engine plus four independent runtime
  adapters and JSONL ledgers.
- Specific manual-review plans: direction, actionable time, entry, stop, T1,
  T2, invalidation geometry, risk distance, source labels, and blockers.
- Adverse-first resolution, 1R partial, 2R final, 0.25R trail after T1,
  transaction friction, idempotent plan IDs, and same-day 16:30 ET time exit.
- Discord qualified-entry and terminal-result alerts, quiet empty scans,
  independent three-failure auto-halts, heartbeat coverage, kill-switch
  handling, and global shadow outcome ingestion.
- One limited-authority Windows task, `\VibeTrade\MnqSmtCisdFamilyShadow`,
  every five minutes from 08:35 through 15:35 CT weekdays, `IgnoreNew`, with a
  10-minute execution limit.

## Live data-path result

The first real proxy run found one CISD-only short on MNQ at 14:05 ET:
entry 29149.00, stop 29156.75, T1 29141.25, T2 29133.50. The adverse-first
resolver recorded `stop_before_t1`, net -$17.20 after modeled friction. This is
exactly why the four ablations run independently: the system records losses
instead of presenting only attractive screenshots.

A Sunday-evening timestamp bug in prior-RTH selection was caught by this run,
fixed to select the latest actual cash session, regression-tested, and followed
by a successful provider-path rerun. All scanner health counters are reset to
zero and none are halted.

## Safety and evidence status

- `execution_enabled=false`
- `can_submit_orders=false`
- `orders_submitted=0`
- Proxy OHLCV outcomes are visible for learning but promotion-ineligible.
- Remaining external blockers: Databento MBO, executable futures BBO, Kenny
  sign-off, and the frozen out-of-sample gate for the composite candidate.

## Shared PDF decision

The Banks top-down guide is useful checklist input but not evidence. Its
direction → structure/location → closed-bar trigger/retest → 5m/15m entry
sequence agrees with the existing framework. Its seven no-trade conditions are
parked for preregistered blocker testing; no frozen rule was changed from
selected social examples.
