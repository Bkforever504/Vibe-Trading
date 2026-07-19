# Vibe-Trading Loop Operating System

Updated: 2026-07-17T23:40:56.738289Z

## Purpose

Run trading research and bot governance as durable loops that observe, verify, remember, and escalate before any risky action.

## Readiness Levels

- L0 - Draft: documented intent only.
- L1 - Report Only: reads state and writes reports/handoffs; no automatic code, risk, or execution changes.
- L2 - Assisted: may propose small changes only after verifier checks and human approval.
- L3 - Unattended: not allowed for execution-capable trading loops.

## Current Summary

- Total loops: 100
- By level: {'L0': 0, 'L1': 82, 'L2': 18, 'L3': 0}
- Execution-capable loops: 2
- Unattended-ready loops: 0

## Operating Rules

- Every loop starts by reading durable state: registry, reports, logs, and memory.
- Every loop writes an append-only run log or JSON report.
- Use a maker/checker split: the builder cannot approve its own signal or code.
- Any execution, risk, live flag, max contracts, or kill-switch change needs explicit Kenny approval.
- Screenshots, social claims, and agent opinions are idea intake only until independently verified.
- Claude and Codex handoffs must include commands, expected outputs, blockers, and no-trade warnings.

## Budget And Kill Criteria

- Default cadence is daily report-only unless a loop has an explicit schedule.
- Stop after one active task unless Kenny explicitly asks for more.
- Pause a loop if tests fail, audit issues appear, state is missing, or the same blocker repeats.
- Do not expand loops just because something is interesting; require an evidence gap.

## Top Review Items

- kalshi_prediction_bot: L1 score=50 next=Add explicit maker/checker or dual-review language before any assisted action.
- point_in_time_option_quotes: L1 score=55 next=Add explicit maker/checker or dual-review language before any assisted action.
- trading_dashboard: L1 score=55 next=Add durable state/run-log path before scheduling.
- distribution_day: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- flip_equity_curve_report: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- hmm_regime_scanner: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- hurst_regime: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- ivr_scanner: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- market_breadth: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- opening_range_breadth: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- preopen_sentiment: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
- relative_volume: L1 score=60 next=Add explicit maker/checker or dual-review language before any assisted action.
