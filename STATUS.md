# Vibe-Trading STATUS

Updated: 2026-08-29T01:05:34.340565Z
Date: 2026-08-28
Verdict: action_required

## Headline

Action required before trusting today's stack output.

## Active Task Cap

Max active tasks: 1

## Next Safe Task

- Priority: P0
- Title: Investigate unhealthy scheduled outputs
- Reason: Health summary is {'disabled': 1, 'error': 1, 'missing': 0, 'ok': 57, 'stale': 7}.
- Suggested action: Open signal-stack-health.json, inspect failing rows, fix only task/log/report plumbing.
- Allowed scope: read_only_or_tests_docs_reports

## Backlog

- [P1] Review guard-block queue: Needs Review Queue has 1 item(s).
- [P1] Inspect weak operational grades: 3 component(s) have weak ops grade/freshness.
- [P1] Run formal promotion review: 7 component(s) are promotion-ready by grades.

## Current State

- Health: {'disabled': 1, 'error': 1, 'missing': 0, 'ok': 57, 'stale': 7}
- Grades: {'ops': {'A': 31, 'B': 5, 'D': 3}, 'evidence': {'A': 2, 'B': 9, 'C': 23, 'F': 5}, 'maturity': {'mature': 6, 'needs_more_signals': 27, 'review_eligible': 2, 'log_building': 4}, 'promotion_ready_count': 7}
- Schedule: {'passed': True, 'aligned_count': 87, 'task_count': 87, 'issue_count': 0}
- Audit: {'passed': True, 'issue_count': 0, 'warning_count': 9}
- Needs review: {'queue_count': 1, 'by_priority': {'low': 1}, 'by_reason': {'spread_quote_unavailable': 1}}

## Forbidden Actions

- Do not enable live trading.
- Do not change risk thresholds, max contracts, kill switches, or manual-reset files.
- Do not promote a scanner into an execution gate without rules/signal_promotion_rules.md.
- Do not wire social/X/PMXT/copy-trader/prediction-market context directly to orders.
- Do not add a new scanner unless the EOD summary identifies a specific evidence gap.

## Stop Conditions

- Stop after one active task.
- Stop if tests fail and report the failure.
- Stop if the task would require live trading, risk, or gate changes.
- Stop if the task needs data that is not present yet.

## Morning Command

```powershell
uv run --no-project python scripts\daily_eod_summary.py --print
uv run --no-project python scripts\nightly_research_loop.py --print
```
