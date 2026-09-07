# Repo Eval: Prefect

**Date:** 2026-09-07
**Repo:** https://github.com/PrefectHQ/prefect
**License:** Apache 2.0
**Stars:** 17k+
**Language:** Python 3.9+

## Idea
Replace Windows Task Scheduler orchestration with Prefect flows. Add retries, dependency graphs, structured observability, idempotency, and event triggers to the scanner/bot scheduling layer.

## Source
Direct evaluation. Motivated by observed error surface in this repo:
- 18 systematic Windows Task Scheduler failures (see mem obs 3095, 3096)
- Python/COM interop root cause (obs 3102)
- Path misconfiguration cascades (obs 3099, 3100)
- ShadowSystemHeartbeat circular self-check risk (obs 3107, 3108)
- No cross-task dependency awareness → operations FAIL cascades observability status (obs 3109)

## Edge (Error Reduction, Not Trading Alpha)
Prefect provides:
- **Automatic retries** with configurable backoff — kills transient COM interop, network, and lock-contention failures
- **Task dependencies** — a task that depends on another cannot silently fire when upstream failed
- **Structured logging + UI** — replaces scraping Windows Event Viewer + task history
- **Idempotency keys** — prevents double-execution during scheduler overlap windows
- **Event-driven triggers** — replaces polling loops (e.g., ShadowSystemHeartbeat) with proper event subscriptions
- **Separation of orchestration from execution** — observability tasks stop failing when operations tasks fail

## Data Needed
None. Pure orchestration layer. Runs on same machine as current scheduler, no new feeds.

## Implementation
**Medium.** Not a rewrite — wrap existing PowerShell/Python entrypoints as Prefect flows. Migrate task-by-task. Existing scripts stay unchanged.

Phase 1 (2-3 days): Prefect server + agent on the trading box, migrate 3 highest-failing tasks (ShadowSystemHeartbeat, PatternGrader, momentum_sweep_runner).

Phase 2 (1 week): migrate remaining scheduled tasks, add dependency DAG.

Phase 3 (optional): Prefect Cloud for remote observability, or self-host UI on existing dashboard box.

## Fit With Current Stack
- Runs alongside Windows Task Scheduler during migration (no big-bang cutover)
- Python-native, integrates with existing venvs (kronos-venv, .agent-reach-venv)
- Free open-source tier is sufficient — Prefect Cloud upgrade optional later
- No conflict with Alpaca, Polygon, Databento, TradingView MCP feeds
- Complements `vibe-trading-scheduler` skill (skill becomes: "edit Prefect flows" instead of "edit .ps1 registrars")

## Ratings (1-5)
- Edge clarity: **5** — directly addresses documented error source
- Implementation complexity: **3** — medium, incremental
- Data availability: **5** — no new data
- Fit with stack: **4** — clean Python integration, minor learning curve

## Verdict
**intake_shadow** → Adopt in phased migration. Start with 3 tasks, prove out for 30 days, then expand.

## Reason
Highest-ROI single change against current observed error surface. Session memory shows recurring scheduler failures with no other durable fix.

## Handoff
See `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-09-07_ERROR_REDUCTION_STACK.md` for implementation plan.
