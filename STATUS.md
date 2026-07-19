# Vibe-Trading STATUS

Updated: 2026-07-18T01:05:01.981609Z
Date: 2026-07-17
Verdict: action_required

## Headline

Action required before trusting today's stack output.

## Active Task Cap

Max active tasks: 1

## Next Safe Task

- Priority: P0
- Title: Reconcile options broker positions with trade state
- Reason: Missing active legs=0; untracked broker legs=1.
- Suggested action: Inspect broker positions and bot-status-snapshot.json; keep entries blocked and do not auto-close or rewrite state.
- Allowed scope: read_only_or_tests_docs_reports

## Backlog

- [P0] Investigate unhealthy scheduled outputs: Health summary is {'error': 0, 'missing': 0, 'ok': 61, 'stale': 1}.
- [P0] Fix market schedule alignment: Schedule alignment issues=1.
- [P1] Review guard-block queue: Needs Review Queue has 4 item(s).
- [P1] Inspect weak operational grades: 2 component(s) have weak ops grade/freshness.
- [P1] Run formal promotion review: 1 component(s) are promotion-ready by grades.

## Current State

- Health: {'error': 0, 'missing': 0, 'ok': 61, 'stale': 1}
- Grades: {'ops': {'A': 32, 'B': 5, 'D': 2}, 'evidence': {'B': 2, 'C': 11, 'D': 22, 'F': 4}, 'maturity': {'needs_more_signals': 31, 'mature': 1, 'review_eligible': 3, 'log_building': 4}, 'promotion_ready_count': 1}
- Schedule: {'passed': False, 'aligned_count': 54, 'task_count': 55, 'issue_count': 1}
- Audit: {'passed': True, 'issue_count': 0, 'warning_count': 1}
- Needs review: {'queue_count': 4, 'by_priority': {'medium': 4}, 'by_reason': {'contracts_above_limit': 2, 'notional_above_limit': 2}}

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
