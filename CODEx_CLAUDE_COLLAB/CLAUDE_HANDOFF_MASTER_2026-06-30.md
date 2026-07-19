# Claude Code Master Handoff - Vibe-Trading 2026-06-30

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Owner today: Codex
Date: 2026-06-30

## Operating Principle

Kenny wants the bot to become best-in-class, then eventually use decent/high leverage only after proof.

Locked rule:

**Edge first. Leverage last.**

Do not loosen execution gates, increase leverage, or enable new live behavior from any research/repo/social-media finding. Everything built today is read-only, evidence-building, or guard intelligence unless explicitly noted.

## Big Picture Today

Today was mostly intelligence-layer work. The stack now has stronger:

- daily market context
- market force aggregation
- sector rotation context
- go-trader-inspired portfolio concentration/status monitoring
- open-source repo research
- PMXT/Polymarket prediction-market research
- rejected-trade intelligence
- regime memory
- daily reports/CSV/leaderboard visibility

No new execution strategy was enabled.
No live unlocks were changed.
No leverage settings were changed.

## Major Builds Completed Today

### 1. Context Scanner / Signal Stack Wiring

Earlier today/new today stack includes:

- GEX scanner
- IVR scanner
- Opening range breadth scanner
- Relative volume scanner
- SEC insider buying scanner
- Social trending scanner + persistence report
- Limitless market scanner
- TTM Squeeze logger
- WaveTrend logger
- SMC logger
- Signal stack health report
- Signal stack leaderboard
- Daily bot activity CSV exporter

Relevant handoffs:

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_CONTEXT_SCANNERS_AND_TODAY_HEALTH_2026-06-30.md`
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_SIGNAL_REGISTRY_AND_EOD_LEDGER_2026-06-30.md`
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_NEW_SIGNAL_STACK_WIRING_2026-06-30.md`

Important current health note:

At last refresh:

- Signal health: `OK=16 STALE=0 MISSING=3 ERROR=0`
- Missing rows are expected until first close-time logs exist:
  - TTM Squeeze
  - WaveTrend
  - SMC

Do not treat those as failures before their scheduled run creates rows.

### 2. Market Force Score

File:

- `scripts/market_force_score.py`

Now aggregates:

1. Opening Range / trend force
2. GEX / level force
3. TTM/WaveTrend/SMC momentum force
4. IVR/VIX volatility force
5. Pre-open/social/relative-volume narrative force
6. Distribution day institutional force
7. Breadth force
8. Sector rotation force

Current live-ish result from today after sector rotation:

- classification: `bullish_lean`
- score: around `2.25`
- confidence: around `9.25`
- coverage: `7/8` or similar depending on close-time rows

Relevant handoffs:

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_MARKET_FORCE_SCORE_2026-06-30.md`
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_SECTOR_ROTATION_RANKER_2026-06-30.md`

### 3. Sector Rotation Ranker

Files:

- `scripts/sector_rotation_ranker.py`
- `scripts/run_sector_rotation_ranker.ps1`
- `agent/tests/test_sector_rotation_ranker.py`

Task:

- `\VibeTrade\SectorRotationRanker`
- weekdays 15:33 CT
- state: Ready

Purpose:

- ranks sector/asset leadership
- feeds Market Force Score
- context only, no execution

First smoke result:

- leadership: `risk_on_leadership`
- force: `+1.5`
- top examples included `XLV`, `XLI`, `XLU`, `XLF`, `SMH`

### 4. Daily Outcome Reviewer

Files:

- `scripts/daily_outcome_reviewer.py`
- `scripts/run_daily_outcome_reviewer.ps1`
- `agent/tests/test_daily_outcome_reviewer.py`

Task:

- `\VibeTrade\DailyOutcomeReviewer`
- weekdays 19:30 CT

Purpose:

- compares Exposure Coach / Market Force posture against actual trade outcomes and guard blocks
- read-only

Relevant handoff:

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_DAILY_OUTCOME_REVIEWER_2026-06-30.md`

### 5. X MCP Setup

Files/configs touched:

- `C:\Users\kenne\.claude\mcp.json`
- `.mcp.json`

Added:

- `x-docs`: `https://docs.x.com/mcp`
- `xapi`: `npx -y @xdevplatform/xurl mcp https://api.x.com/mcp`

Backups:

- `*.bak-20260630-115158`

Current status:

- X docs MCP should work after Claude restart.
- X API MCP requires official X developer auth/cached xurl credentials.
- Kenny noticed it is not free. Do not spend money or add paid API until explicit approval.

Relevant handoff:

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_X_MCP_SETUP_2026-06-30.md`

### 6. go-trader Inspired Risk / Status Layer

Source evaluated:

- `richkuo/go-trader`

Decision:

- do not migrate
- extract the useful idea: central portfolio/status reporting

Files built:

- `scripts/portfolio_concentration_monitor.py`
- `scripts/run_portfolio_concentration_monitor.ps1`
- `scripts/bot_status_snapshot.py`
- `scripts/run_bot_status_snapshot.ps1`
- `agent/tests/test_portfolio_concentration_monitor.py`
- `agent/tests/test_bot_status_snapshot.py`

Integrated into:

- `scripts/signal_stack_health_report.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`

Tasks:

- `\VibeTrade\PortfolioConcentrationMonitor`
  - weekdays 11:05 CT
  - state: Ready
- `\VibeTrade\BotStatusSnapshot`
  - weekdays 19:35 CT
  - state: Ready

First live Alpaca concentration smoke:

- risk: `normal`
- positions: `5`
- gross option value: about `$2,302`, `2.577%` of equity
- net directional beta: about `$909.55`, `1.018%` of equity
- underlyings: TSLA, SPY, IWM

Relevant handoff:

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_GO_TRADER_RISK_STATUS_LAYER_2026-06-30.md`

### 7. Open-Source Trading Repo Scan

User asked to use `last30days` and other research for Reddit/TikTok/open-source trading automation repos.

Files written:

- `research/trading_automation_repo_scan_2026-06-30.md`
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_OPEN_SOURCE_TRADING_REPO_SCAN_2026-06-30.md`

Research result:

- `last30days` result was thin:
  - Reddit: generic threads only
  - TikTok: no useful repo hits surfaced
  - GitHub unavailable in the skill without token
  - web backend limited
- Codex supplemented with public GitHub API + README checks.

Best repo ranking:

1. PMXT - prediction-market ccxt-style adapter
2. Polymarket `py-clob-client`
3. OpenBB
4. NautilusTrader
5. CuteMarkets `cutebacktests`
6. Hummingbot/Freqtrade/Lumibot/Qlib as references/sandboxes only

Do not run random TikTok/GitHub AI bot repos with keys.

### 8. PMXT Probe + Polymarket Wallet Tracker Hardening

Files built:

- `tools/pmxt-probe/package.json`
- `tools/pmxt-probe/pmxt_schema_probe.mjs`
- `scripts/pmxt_market_schema_probe.py`
- `scripts/run_pmxt_market_schema_probe.ps1`
- `agent/tests/test_pmxt_market_schema_probe.py`

Files modified:

- `strategies/polymarket_wallet_tracker.py`
- `agent/tests/test_polymarket_wallet_tracker.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`

PMXT probe result:

- PMXT installed only inside `tools/pmxt-probe` sandbox.
- `npm install` reported 26 vulnerabilities in sandbox dependencies.
- Local PMXT mode timed out / wanted `pmxt-core` sidecar.
- Hosted mode with `PMXT_BASE_URL=https://api.pmxt.dev` returned `Too Many Requests` without a PMXT key.

Verdict:

- PMXT is not ready as a free backbone.
- Do not schedule it.
- Do not add credentials.
- Keep it manual/read-only.

Polymarket hardening:

- Wallet tracker now records endpoint provenance:
  - `data_source`
  - `data_quality`
  - `endpoint_attempts`
  - `closed_positions_survivorship_warning`
- Priority:
  1. `data-api/activity` - primary all-activity source
  2. `clob/trades` - fallback
  3. closed positions only - survivorship warning

Relevant handoff:

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_PMXT_AND_POLYMARKET_HARDENING_2026-06-30.md`

### 9. Regime Memory + Rejected Trade Intelligence

This was the last major build of the day.

Files built:

- `scripts/regime_memory_report.py`
- `scripts/run_regime_memory_report.ps1`
- `scripts/rejected_trade_intelligence.py`
- `scripts/run_rejected_trade_intelligence.ps1`
- `agent/tests/test_regime_memory_report.py`
- `agent/tests/test_rejected_trade_intelligence.py`

Integrated into:

- `scripts/signal_stack_health_report.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`

Tasks:

- `\VibeTrade\RegimeMemoryReport`
  - weekdays 19:40 CT
  - state: Ready
- `\VibeTrade\RejectedTradeIntelligence`
  - weekdays 19:45 CT
  - state: Ready

Regime Memory purpose:

- learns bot outcomes by regime:
  - Market Force classification
  - breadth status
  - distribution regime
  - sector rotation leadership
  - exposure posture
  - outcome verdict
  - P&L bucket

First run:

- only 1 day available
- correctly reports `LOG BUILDING`
- do not draw conclusions until 30+ days ideally

Rejected Trade Intelligence purpose:

- reviews guard blocks by reason/context
- labels rejections:
  - `likely_good_rejection`
  - `reasonable_rejection`
  - `possibly_too_strict`
  - `safety_lock`
  - `needs_review`

First run:

- blocks: `145`
- `likely_good_rejection`: `71`
- `reasonable_rejection`: `55`
- `safety_lock`: `15`
- `needs_review`: `4`

Top reasons:

- `confidence_below_minimum`: 55, reasonable
- `duplicate_symbol_exposure`: 22, likely good
- `portfolio_kill_switch`: 17, likely good
- `live_execution_not_enabled`: 15, safety lock
- `daily_loss_limit`: 15, likely good
- `spread_too_wide`: 13, likely good

Current conclusion:

- Guard stack is mostly doing its job.
- No evidence to loosen gates.
- `possibly_too_strict` or `needs_review` is a research prompt only.

Relevant handoff:

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_REGIME_AND_REJECTION_INTELLIGENCE_2026-06-30.md`

## Verification Summary Today

Focused test runs that passed:

- Sector rotation / Market Force: `20 passed` earlier
- go-trader risk/status layer: `11 passed`
- PMXT + Polymarket hardening: `16 passed`
- Regime Memory + Rejected Intelligence integrations: `14 passed`

Compile checks passed for touched scripts during each build.

Latest reporting refresh:

- Signal health: `OK=16 STALE=0 MISSING=3 ERROR=0`
- CSV for 2026-06-30: `61` events
- CSV includes:
  - `risk_context`
  - `status_review`
  - `intelligence_review`
  - `prediction_market_context`

## Current Scheduled Task Additions Today

New or newly relevant tasks include:

- `SectorRotationRanker` - weekdays 15:33 CT
- `DailyOutcomeReviewer` - weekdays 19:30 CT
- `PortfolioConcentrationMonitor` - weekdays 11:05 CT
- `BotStatusSnapshot` - weekdays 19:35 CT
- `RegimeMemoryReport` - weekdays 19:40 CT
- `RejectedTradeIntelligence` - weekdays 19:45 CT

All verified Ready when created.

## Important Safety Constraints For Claude

Do not:

- enable live trading
- loosen guard thresholds
- schedule PMXT
- add PMXT credentials
- use X paid API without explicit approval
- run random AI trading bot repos with broker/exchange keys
- promote any repo/social claim directly into execution
- use Regime Memory with only 1 day of data as a gate
- interpret `possibly_too_strict` as permission to loosen gates

Do:

- keep new intelligence reports read-only
- let logs accumulate
- inspect `needs_review` guard blocks manually
- verify close-time TTM/WaveTrend/SMC rows after first scheduled runs
- use reports to build evidence, not excitement

## Best Next Steps

1. After market close, verify TTM/WaveTrend/SMC generated first rows.
2. Let Regime Memory accumulate at least 3 days before reading it casually, 30+ days before making decisions.
3. Inspect the 4 `needs_review` rejected-trade cases manually.
4. Compare Polymarket tracker endpoint behavior against official `Polymarket/py-clob-client` source before adding wallet-cluster consensus.
5. Consider OpenBB context probe later, but do not add more signals until current reports prove useful.
6. Keep focus on evidence quality and guard behavior before leverage.

## Bridge Command For Claude

Claude should run:

```powershell
python scripts\agent_bridge.py inbox --for claude
```

Then start with this file:

`CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_MASTER_2026-06-30.md`
