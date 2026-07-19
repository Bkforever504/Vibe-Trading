# Market schedule alignment added

- id: `20260701T002726Z-market-schedule-alignment-added-67976c99`
- from: `codex`
- to: `claude`
- created_at: `2026-07-01T00:27:26Z`

Market schedule alignment layer added.

Files:
- scripts/market_schedule_alignment.py
- scripts/run_market_schedule_alignment.ps1
- agent/tests/test_market_schedule_alignment.py

Integrations:
- research/signal_registry.json includes Market Schedule Alignment
- signal_stack_health_report includes Schedule Align
- daily_eod_summary reads market-schedule-alignment.json and can downgrade verdict if schedule timing breaks
- Scheduled task: \VibeTrade\MarketScheduleAlignment weekdays 08:10 CT and 19:58 CT, Ready

Outputs:
- C:\Users\kenne\.vibe-trading\reports\market-schedule-alignment.json
- data/market_schedule_alignment_log.jsonl

Current result:
- passed=True
- aligned=39/39
- issues=0
- warnings=0

Health after integration:
- OK=23, STALE=0, MISSING=0, ERROR=0

EOD summary remains green and now includes schedule_alignment.

Note: schedule checker assumes regular US cash session timing in America/Chicago. Holidays/half-days are still a manual watch item unless we add an exchange calendar later.
