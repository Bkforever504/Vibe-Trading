# Daily signal grades added

- id: `20260630T233104Z-daily-signal-grades-added-053141c3`
- from: `codex`
- to: `claude`
- created_at: `2026-06-30T23:31:04Z`

Daily grading layer added.

Files:
- scripts/signal_stack_grades.py
- scripts/run_signal_stack_grades.ps1
- agent/tests/test_signal_stack_grades.py

Integrations:
- research/signal_registry.json includes Signal Stack Grades
- signal_stack_health_report includes Grades
- export_daily_bot_activity_csv includes signal_stack_grades intelligence_review rows
- Scheduled task: \VibeTrade\SignalStackGrades weekdays 19:55 CT, Ready

Outputs:
- C:\Users\kenne\.vibe-trading\reports\signal-stack-grades.json
- C:\Users\kenne\.vibe-trading\reports\signal-stack-grades.csv
- data/signal_stack_grades_log.jsonl

Current grade snapshot:
- Ops grades: A=26, B=5
- Evidence grades: D=5, F=26
- Stages: log_building=30, needs_more_signals=1
- promotion_ready=0

Interpretation: stack is operationally healthy, but evidence is intentionally immature because most scanners have only 1-10 rows. Do not treat low evidence grades as failures yet; they are sample-size warnings.

Verification:
- Health: OK=21, STALE=0, MISSING=0, ERROR=0
- Execution audit: passed=True, issues=0, warnings=1 expected read-only Alpaca warning
- Focused tests: 11 passed
