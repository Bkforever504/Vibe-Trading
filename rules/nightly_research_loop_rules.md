# Nightly Research Loop Rules

Last updated: 2026-06-30

## Purpose

The nightly loop is a handoff generator. It reads the daily reports, writes `STATUS.md`, and creates a capped research queue for Codex and Claude.

It is not an autonomous trading system.
It is not an autonomous code executor.
It is not allowed to promote signals.

## Allowed

- Summarize daily EOD reports.
- Identify one safe next task.
- Queue read-only review work.
- Point agents at failing health, schedule, audit, or grade items.
- Recommend tests/docs/report fixes.
- Produce handoff notes.

## Forbidden Without Kenny Approval

- Enabling live trading.
- Changing `ALPACA_PAPER`, live execution flags, or Kalshi live flags.
- Raising max contracts, risk percent, notional caps, or daily loss limits.
- Disabling kill switches or deleting manual-reset files.
- Promoting a scanner into an execution gate.
- Wiring social/X/PMXT/copy-trader/prediction-market signals directly to orders.
- Adding new scanners when the EOD summary is green and evidence is still building.

## Loop Brakes

- Maximum active tasks per nightly loop: `1`.
- Stop if tests fail.
- Stop if the task requires missing data.
- Stop if the task would affect execution, sizing, risk, or gates.
- Stop if another agent has an active bridge claim.

## Review Path

1. Nightly reports run.
2. `scripts/nightly_research_loop.py` writes `STATUS.md`.
3. Claude/Codex read `STATUS.md`.
4. One safe task may be handled.
5. Any execution-impacting proposal requires explicit Kenny approval.

## Golden Rule

The loop may improve the research machine. It may not make the trading machine more aggressive without proof and approval.
