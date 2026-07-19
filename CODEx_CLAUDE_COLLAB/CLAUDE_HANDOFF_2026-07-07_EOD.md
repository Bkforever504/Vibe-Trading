# Claude Code Handoff — July 7, 2026 EOD

Read `KNOWLEDGE/VIBE_TRADING_AGENT_MEMORY.md` first.

---

## Stack Verification State

```
Health:        OK=43  STALE=0  MISSING=0  ERROR=0
Gate audit:    passed=True  signals=86  issues=0  warnings=1 (known read-only portfolio warn)
Tests:         44 passed (full suite per Codex), 10 passed (dashboard+gate)
Dashboard:     C:\Users\kenne\.vibe-trading\dashboard.html  writes clean
```

---

## KILL SWITCH — DO NOT RESET AUTOMATICALLY

```
status:               killed
reason:               max_daily_loss
daily_pnl:            -$960.00
hard_limit:           -$750.00
triggered:            2026-07-07T15:05:16Z
manual_reset_required: true
```

Tomorrow's entries are blocked until user reviews and explicitly resets the kill switch.
Do not add code to auto-reset. Do not lower the hard daily loss limit.

---

## Two Pending Admin Tasks (must run as Administrator)

These scheduled tasks were not registered because `schtasks /create \VibeTrade\` requires elevation.
Registration scripts exist — run once in an elevated PowerShell, then come back and add health entries.

```powershell
# Run as Administrator:
.\scripts\register_cheap_asymmetry_task.ps1    # \VibeTrade\CheapAsymmetryScanner   19:08
.\scripts\register_flip_bot_learning_task.ps1  # \VibeTrade\FlipBotLearningReport   19:15
```

After confirming both show `Status: Ready` in Task Scheduler, add to `scripts/signal_stack_health_report.py`:

```python
{
    "name": "Cheap Asymmetry",
    "task": r"\VibeTrade\CheapAsymmetryScanner",
    "log": ROOT / "data" / "cheap_asymmetry_scan_log.jsonl",
    "kind": "evening",
},
{
    "name": "Flip Bot Learning",
    "task": r"\VibeTrade\FlipBotLearningReport",
    "log": ROOT / "data" / "flip_bot_learning_log.jsonl",
    "kind": "evening",
},
```

---

## What Was Built Today (July 7)

All read-only unless explicitly noted. Codex built, Claude Code integrated into dashboard + health.

| Script | Report JSON | Scheduler Task | Status |
|---|---|---|---|
| `market_catalyst_calendar.py` | `market-catalyst-calendar.json` | `\VibeTrade\MarketCatalystCalendar` 8:20 AM | health=ok |
| `higher_timeframe_market_map.py` | `higher-timeframe-market-map.json` | `\VibeTrade\HigherTimeframeMarketMap` 8:42 AM | health=ok |
| `candlestick_context_scanner.py` | `candlestick-context.json` | `\VibeTrade\CandlestickContextScanner` 10:07 AM | health=ok |
| `daily_edge_orchestrator.py` | `daily-edge-orchestrator.json` | `\VibeTrade\DailyEdgeOrchestrator` 10:14 AM | health=ok |
| `loop_closure_report.py` | `loop-closure-report.json` | (Codex registered) | health=ok |
| `agent_incentive_safety_audit.py` | `agent-incentive-safety-audit.json` | (Codex registered) | health=ok |

Also built earlier this session (July 6–7):
`cheap_asymmetry_scanner.py`, `flip_bot_learning_report.py`, `creator_watchlist_runner_scanner.py`,
`nightly_alpha_factory.py`, `loop_readiness_audit.py`, `mahoraga_repo_intake_audit.py`,
`openalice_repo_intake_audit.py`, `market_catalyst_calendar.py`

---

## Dashboard Nav (22 sections, all wired)

Overview · P/L · Charts · Risk · Bots · Flip Trades · IWM Trades · Positions · Health ·
**Mastery** · **Consensus** · Grades · Hot Tickers · **Asymmetry** · **Learning** · **Watchlist** ·
**Alpha** · **Closure** · **Loops** · **Mahoraga** · **OpenAlice** · **Incentives** · Review

Bold = added this session. All degrade gracefully when JSON missing.

---

## July 6–7 Trade Reality

**July 6:**
- Trade 1: SPY CALL — peaked +66%, exited +17% (poor capture). Ratchet installed: `PROFIT_PROTECT_ARM_PCT=40`.
- Trade 2: SPY CALL — same-day re-entry loss -$242.50. Same-day re-entry block installed.
- Net: -$175.00

**July 7:**
- SPY PUT closed -$142.50 (date exit + bull reclaim miss).
- Bull reclaim miss fixed: `BULL_TREND_MIN_CONFIDENCE=8.0`, all three leaders (SPY/QQQ/IWM) required.
- Kill switch triggered at -$960 for the day.

---

## Key Governance Rules (permanent)

- `LIVE_EXECUTION_ENABLED = False` default everywhere.
- `MAX_CONTRACTS = 5`, `max_risk_pct = 0.02` (2%). Do not raise.
- `promising_not_ready` scanners stay `shadow_only`. They do not influence entries.
- No scanner → execution gate without `rules/signal_promotion_rules.md` promotion criteria.
- No social/creator/PMXT signal routes to orders.
- Builder cannot self-approve. Dual Claude + Codex review required.
- L3 unattended blocked for trading execution loops.
- Do not auto-reset kill switch.

---

## Evidence Progress

**Cheap Asymmetry Scanner** — day 1 of 30 needed:
- AAPL CALL: cost=$31, best return=538.7% (candidate, not goal_match — capture not proven)
- META CALL: cost=$23, best return=243.5% (candidate)
- Goal match: cost $10-50 AND simulated captured return 500%+ AND spread ≤20¢
- Promotion gate: 30 trading days + 10 completed samples/symbol + dual review + explicit approval

**Shadow Consensus Gate** — first scheduled run is 2026-07-08 10:12 AM. Verify logs after market.

---

## Upcoming Macro Catalyst Dates (from market_catalyst_calendar.py)

| Date | Event | Impact |
|---|---|---|
| Jul 14 | CPI Release (June 2026) 8:30 AM ET | HIGH — no new short premium before release |
| Jul 28 | FOMC Meeting Day 1 | HIGH — reduce size, stand aside |
| Jul 29 | FOMC Decision + Powell 2:00 PM ET | HIGH — stand aside until post-decision |
| Jul 30 | GDP Advance Q2 + PCE 8:30 AM ET | HIGH — double binary event |

---

## Next Session Starting Points (priority order)

1. **Kill switch review** — user decides whether to reset before July 8 open.
2. **Verify new Market Mastery scanners ran** — check logs after 10:07 AM for candlestick/HTF/consensus.
3. **Register two pending admin tasks** — CheapAsymmetryScanner + FlipBotLearningReport, then add health entries.
4. **AAPL cheap asymmetry day 2** — observe only, do not promote.
5. **Options Bot directional playbook** — next big upgrade: add long call/put candidate path as read-only shadow. Do not force credit spreads on trend expansion days.
6. **OpenAlice issue board** — top queued upgrade: `vibe_research_issue_board` (file-backed, no agent scheduler).

---

## Start-of-Session Commands

```powershell
python scripts\generate_dashboard.py
python scripts\signal_stack_health_report.py
python scripts\execution_gate_audit.py --fail-on-issues --print
python scripts\market_catalyst_calendar.py --print
python -m pytest agent\tests\ -q --tb=short 2>&1 | tail -5
```

---

## What NOT to Do

- Do not reset kill switch automatically.
- Do not raise MAX_CONTRACTS or max_risk_pct.
- Do not promote any scanner to execution gate without full evidence gate.
- Do not let `promising_not_ready` influence live entries.
- Do not add health entry for tasks not yet confirmed Ready in Task Scheduler.
- Do not wire candlestick/HTF/catalyst context directly to orders — shadow first.
