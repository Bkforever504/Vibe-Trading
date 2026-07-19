---
name: vibe-trading-scheduler
description: Use when editing Windows Task Scheduler jobs, PowerShell runners, cadence, market-hours behavior, or scanner automation.
---

# Vibe-Trading Scheduler

## Task Scheduler Layout
All tasks live under `\VibeTrade\` folder in Windows Task Scheduler.
View: `schtasks /query /fo LIST /tn "\VibeTrade\" /v`

## PS1 Runner Pattern
Every script has a corresponding `scripts/run_<name>.ps1`:
```powershell
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
uv run --no-project python scripts/<name>.py
```
For scripts needing numpy/pandas: use `python scripts/<name>.py` (system Python, not uv).

## uv Usage Rules
| Script type | Runner |
|---|---|
| Pure Python (no numpy) | `uv run --no-project python scripts/...` |
| Needs yfinance/pandas | `uv run --no-project --with yfinance --with pandas python scripts/...` |
| Needs numpy | `python scripts/...` (system Python — SAC blocks uv+numpy) |
| HMM / PCA runners | `python scripts/...` only |

## Market-Hours Aware Scheduling
Intraday scanners must check `_is_market_closed(date.today())` at runtime.
Weekend/holiday runs should log `{"status": "market_closed"}` and exit cleanly.
This prevents error entries in health logs on Saturdays, Sundays, and NYSE holidays.

## Adding a New Scheduled Task
1. Write `scripts/run_<name>.ps1`
2. Register task: `schtasks /create /tn "\VibeTrade\<Name>" /tr "powershell -File scripts\run_<name>.ps1" /sc DAILY /st HH:MM`
3. Add signal entry to `scripts/signal_stack_health_report.py` SIGNALS list with correct task name
4. Test the runner manually first: `.\scripts\run_<name>.ps1`
5. Run health check: `python scripts/signal_stack_health_report.py --no-write`

## Dashboard Generation Task
Task: `\VibeTrade\GenerateDashboard`
Regenerates `~/.vibe-trading/dashboard.html` on schedule.
Manual: `python scripts/generate_dashboard.py`

## Fable5 Intelligence Stack Orchestrator
`scripts/run_fable5_intelligence_stack.ps1` — runs full read-only stack in order:
strategy_leak_audit → hmm_regime → pca_market_forces → prediction_market → missed_banger_review → agent_trade_debate → execution_gate_audit

## Red Flags
- PS1 runner that uses `uv run --with numpy` (SAC blocks)
- Task scheduled without a corresponding health-check entry (becomes invisible to monitoring)
- Runner that doesn't `Set-Location $projectRoot` (relative path breakage)
