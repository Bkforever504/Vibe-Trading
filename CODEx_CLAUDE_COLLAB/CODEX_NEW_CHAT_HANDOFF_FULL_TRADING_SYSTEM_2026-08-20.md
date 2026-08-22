# New Chat Handoff: Full Trading System

Date: 2026-08-20 America/Chicago (prepared after the UTC date changed to
2026-08-21)

Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

This is the current source-of-truth handoff for a new Codex chat. Read it before
changing code, strategy settings, schedules, evidence labels, or order authority.

## Mission

Build a reliable, evidence-driven trading research and decision-support system
that:

1. Finds high-quality opportunities across liquid stocks, ETFs, options, and
   index futures.
2. Presents a simple manual decision card with the setup, confirmation, trigger,
   invalidation, target, instrument, freshness, and reasons.
3. Continuously records accepted and rejected opportunities so missed trades,
   fills, exits, and counterfactuals can be reviewed.
4. Promotes a strategy only after causal, executable, post-cost, forward evidence
   passes frozen gates.
5. Keeps autonomous trading bounded, reconciled, idempotent, and fail-closed.

The user wants the dashboard and manual trade-review workflow to be the primary
focus while the bots and shadow loggers continue collecting evidence. There is
no guarantee of daily profit, no perfect prediction system, and no permission to
manufacture positive backtests or probabilities.

## Current Honest State

- The read-only trading cockpit and its simplified command layer are built.
- The local dashboard backend is listening on `0.0.0.0:8899` and was restarted
  after the schema-6 deployment.
- The authenticated remote gateway is listening on port `8898`; its existing
  supervisor task is running. The stale Cloudflare quick tunnel was rotated,
  and authenticated external dashboard and quote round-trips passed on
  2026-08-20 at approximately 21:41 CT without exposing the URL or token.
- The current cockpit command is based on stale evidence and correctly returns
  `STAND_ASIDE`; it is not a trade recommendation.
- All opportunity-intelligence, profitability-control, momentum-ensemble,
  Topstep-readiness, and GEX research reports inspected for this handoff have
  `execution_enabled=false` and `can_submit_orders=false`.
- The latest profitability control plane selects cash and counterfactual
  collection, not capital deployment.
- Topstep readiness is blocked. No futures candidate has passed the promotion
  gate.
- The options volatility-premium lane is suspended in the latest lifecycle
  report. A high win rate did not overcome large losses.
- No newly tested intelligence policy is a forward-validated edge.

Do not describe the system as profitable, production-ready, or able to make
money every day. Operational capability and research coverage have improved;
profitability is still evidence-capped.

## Git and Worktree Warning

Branch: `main`

HEAD: `af15fdff0bd9be1907c1707b31bd34e00b34f412`

Recent committed anchors:

- `af15fdf` Add Claude handoff for strategy replication league
- `b6c5797` Add public strategy replication league
- `979951e` Add Claude handoff for SPY execution hardening
- `7315e14` Harden SPY options execution and evidence gates
- `ed80578` Update agent memory
- `677bf08` Harden Flip bot Monday operations
- `860deca` Add full strategy handoff for 2026-08-08
- `562441a` Demote one options-liquidity condition to advisory
- `27d2a71` Fix three Flip-bot blockers

The working tree is far ahead of HEAD and extremely dirty. Snapshot immediately
before this handoff file was added, using `git status --short` (which collapses
untracked directories):

- 826 reported status entries
- 186 tracked modification/deletion entries
- 640 untracked entries

Most post-August-8 dashboard, research, scheduler, test, and evidence work is not
represented by HEAD. Many changed files under `data/` are generated logs.

Rules for the next chat:

- Never run `git reset --hard`, `git checkout --`, `git clean`, or an equivalent.
- Do not revert or overwrite changes merely because they are uncommitted.
- Inspect the current file before editing it.
- Keep generated logs and user research untouched unless the task specifically
  requires them.
- Before any commit, isolate source/test/document changes from generated data and
  inspect the complete staged diff.

## Non-Negotiable Safety Boundaries

1. No forced trades. Cash and stand-aside are valid outcomes.
2. Social-media screenshots, videos, Discord posts, and claimed PnL are hypothesis
   sources only. They cannot establish edge or authorize a trade.
3. Never tune a negative result until it becomes positive and then present it as
   independent evidence.
4. Never fabricate a probability, GEX level, option strike, fill, no-trade zone,
   catalyst, target, or stop when its source is unavailable.
5. Stale or incomplete evidence must degrade to `WAIT`, `STAND_ASIDE`, or
   `RESEARCH_ONLY`, never a favorable assumption.
6. Portfolio kill switches, reconciliation failures, malformed state,
   unavailable mandatory context, liquidity failures, event controls, and
   multi-warning stand-asides remain fail-closed.
7. Dashboard and research pipelines remain read-only. They do not call brokers.
8. Any future paper or live promotion requires a frozen specification, causal
   timestamps, executable prices, realistic friction, untouched forward data,
   risk limits, broker reconciliation, and explicit human approval.
9. Never expose credentials, API keys, remote-dashboard tokens, account IDs, or
   broker secrets in chat, logs, tests, commits, or this handoff.

## System Architecture

### 1. Market and Context Inputs

The system combines existing point-in-time artifacts rather than allowing an
LLM to invent a trade:

- Alpaca market/account/options data where credentials and entitlements permit.
- Databento historical MES research files and manifests.
- Yahoo/yfinance research proxies where explicitly labeled as proxies.
- Higher-timeframe market maps, market force, breadth, sector rotation, GARCH,
  HMM/Hurst regimes, volatility and IV/RV context.
- Catalysts, event calendars, opening gaps, relative volume, price action,
  candlestick context, liquidity feasibility, option surfaces, GEX scans, and
  shadow consensus.
- Social and external-trader intake for discovery only, with provenance and
  outcome review kept separate from execution authority.

Important limitation: source availability, timeliness, options NBBO quality,
open-interest coverage, and point-in-time catalyst quality vary. Every consumer
must expose freshness and completeness.

### 2. Opportunity Discovery

Key current modules:

- `scripts/premarket_opportunity_radar.py`
- `scripts/intraday_opportunity_radar.py`
- `scripts/trade_signal_generator.py`
- `scripts/daily_stock_screener.py`
- `scripts/daily_options_universe_ranker.py`
- `scripts/event_gap_continuation_shadow.py`
- `scripts/bottom_reversal_investigator.py`
- `scripts/bottom_reversal_forward_tracker.py`
- `scripts/simple_price_action_alerts.py`
- `scripts/daily_trade_plan_snapshot.py`
- `scripts/momentum_edge_ensemble_shadow.py`
- `scripts/gex_scanner.py`
- `scripts/gex_level_reaction_shadow.py`

The radar searches more than a static mega-cap list. It ranks liquid universe
candidates, event gaps, relative volume, momentum/structure, liquidity, spread
quality, catalysts, and source breadth. QuantMuse's useful idea was adopted as
observe-only cross-sectional factor agreement. QuantMuse itself was rejected as
a runtime/backtest/execution dependency; see the audit below.

### 3. Read-Only Trading Cockpit

Backend normalization:

- `scripts/live_trading_cockpit.py`
- API route: `GET /trading/dashboard`
- Raw whitelisted source route: `GET /trading/dashboard/sources/{source_name}`
- API server: `agent/api_server.py`

Frontend:

- `frontend/src/pages/TradingCockpit.tsx`
- `frontend/src/lib/api.ts`
- route wiring and layout live under `frontend/src/`

The cockpit aggregates reports from `~/.vibe-trading/reports/`, including bot
status, daily edge, screeners, options universe, trade signals, premarket and
intraday radar, price-action alerts, move coverage, bottom reversals, market
force/breadth/sector/HTF context, catalysts, GARCH, GEX-related context, signal
health, execution audits, readiness, reconciliation, portfolio risk, options
liquidity/surface/premium, shadow consensus, and the daily plan.

The top command card has exactly one state:

- `READY_TO_REVIEW`
- `WAIT`
- `NO_CHASE`
- `INVALID`
- `RESEARCH_ONLY`
- `STAND_ASIDE`

It shows:

- symbol, direction, setup, grade, and score;
- trigger, invalidation, and target;
- instrument/contract status;
- confirmation and next action;
- evidence timestamp, age, and freshness;
- dealer/GEX context only when provenance qualifies it;
- execution disabled and order count zero.

Safety details implemented in `scripts/live_trading_cockpit.py`:

- Only source-defined no-trade zones are displayed. The cockpit never invents
  one.
- Completed-bar/generated evidence older than 20 minutes forces otherwise
  actionable states to `STAND_ASIDE`.
- GEX routing requires provenance-qualified 0DTE data. Missing GEX is displayed
  as unavailable, not inferred.
- Current schema version is 5.

At the last sanity check the command was:

- `STAND_ASIDE`
- ETHA bullish opening-range-breakout candidate, grade B+, score 73.8
- trigger 17.57, invalidation 17.52, target 17.67
- last evaluated bar 2026-08-20T19:55:00Z
- evidence age approximately 16,755 seconds
- next action: refresh scanners
- GEX unavailable due to no provenance-qualified scan
- simple-signal counts: 0 confirmed, 95 invalid, 5 waiting

This is an example of the freshness control working, not a current setup.

### 4. Dashboard Hosting

Local backend launcher:

- `scripts/run_live_trading_dashboard_backend.ps1`
- listens on port 8899

Remote read-only layer:

- `scripts/remote_dashboard_gateway.py`
- `scripts/run_remote_trading_dashboard_supervisor.ps1`
- `scripts/run_remote_dashboard_fallback_tunnel.ps1`
- `scripts/register_remote_trading_dashboard_task.ps1`
- `scripts/register_remote_dashboard_fallback_task.ps1`

The gateway serves the built frontend, proxies only dashboard GET routes, uses a
token/API-key boundary, and rejects write methods. The Cloudflare quick tunnel
is convenience infrastructure, not a durable deployment.

Runtime secret files are under `~/.vibe-trading/`. Do not print their contents.

Current verified state after the dashboard blueprint deployment:

- port 8899: listening; schema 6 dashboard, quotes, and bars probed green
- port 8898: listening; local authenticated dashboard and quote proxy green
- `Vibe-Trading-Remote-Dashboard`: task state `Running`
- remote URL file rotated at 2026-08-20 21:39 CT
- public DNS: published; authenticated HTTPS dashboard and quote probes green

The Cloudflare quick tunnel remains convenience infrastructure and may rotate;
re-probe it before treating any saved URL as durable.

### 5. Alpaca Options and Equity Automation

Primary existing strategy engine:

- `strategies/flip_bot.py`

Associated launchers and monitoring:

- `scripts/run_flip_bot_entry.ps1`
- `scripts/run_flip_bot_monitor.ps1`
- `scripts/run_flip_bot_exploration.ps1`
- `scripts/harden_flip_bot_scheduler.ps1`

Relevant safety/learning layers include execution-gate audits, paper/live
readiness, position reconciliation, idempotent client order IDs, limit-order
concession logic, bid-based stop/profit-protect evaluation, crash alerts, log
rotation, state corruption alerts, shadow PnL evaluation, exit-quality review,
feature ablation, missed-move review, and learning reports.

Do not assume Alpaca traded today merely because tasks ran. Determine the truth
from broker order/fill records, current positions, reconciliation, task result
codes, and decision logs. A scheduler success is not a fill.

Other options strategy/research modules include:

- `strategies/iwm_options_bot.py`
- `strategies/spy_theta_harvester.py`
- `strategies/spy_iron_condor.py`
- `strategies/spy_wheel.py`
- `strategies/spy_weekend_vol.py`
- `strategies/vix_call_hedge.py`
- `strategies/spy_0dte_pm_spread.py`
- `scripts/options_shadow_twin.py`
- `scripts/adaptive_options_shadow_playbook.py`
- options IV/RV, liquidity, surface, premium-level, event, and shadow reports

These modules are not collectively approved for live deployment. Their current
individual lifecycle and reconciliation status must be checked before any
paper-routing change.

### 6. Shadow Evidence and Options Twin

The options shadow twin records candidate-specific profit targets and stop
policies, midpoint and executable marks, entry and close friction, deflated
Sharpe, drawdown, loss streaks, and time-bucket performance.

Key paths:

- `scripts/options_shadow_twin.py`
- `data/options_shadow_twin_log.jsonl`
- `scripts/adaptive_options_shadow_playbook.py`
- `data/adaptive_options_shadow_playbook_log.jsonl`

The current opportunity-intelligence report warns that volatility-premium
evidence has a poor payoff distribution despite a high win rate. Never promote
based on win rate alone.

### 7. Futures and Topstep

Key paths:

- `strategies/topstep_prop_bot.py`
- `strategies/topstepx_practice_adapter.py`
- `strategies/topstepx_market_recorder.py`
- `strategies/topstep_replay_backtester.py`
- `strategies/topstep_combine_simulator.py`
- `scripts/topstepx_practice_probe.py`
- `scripts/topstepx_trade_reconciliation.py`
- `scripts/topstep_readiness_report.py`
- `scripts/run_topstep_evidence_pipeline.ps1`
- `scripts/run_topstepx_market_recorder.ps1`

Latest `data/topstep_readiness_report.json` status: `blocked`.

Recorded blockers:

- TopstepX credentials missing
- personal-device confirmation missing
- market recorder not collecting
- no broker-confirmed round trips
- no strategy passed the promotion gate

The report says not to buy a Combine or enable Practice routing until those
conditions are resolved. Preserve that decision unless fresh evidence and the
preregistered process explicitly change it.

### 8. MES Reopen/VIX Research Correction

Authoritative correction:

- `CODEx_CLAUDE_COLLAB/CODEX_CORRECTION_MES_OVERNIGHT_EDGE_2026-08-17.md`

Current valid paths:

- `research/MES_REOPEN_VIX_FILTER_PREREGISTRATION_2026-08-17.md`
- `research/mes_reopen_vix_holdout.py`
- `research/mes_reopen_sensitivity.py`
- `strategies/mes_reopen_vix_shadow_logger.py`
- `data/mes_reopen_vix_holdout.json`
- `data/mes_reopen_sensitivity.json`
- `data/mes_reopen_vix_shadow_log.jsonl`

Correct schedule:

- entry Monday-Thursday at 17:06 CT
- exit Tuesday-Friday at 08:36 CT

The old 15:55 ET close-to-open logger was causally invalid and violated Topstep's
flat boundary. It was deleted. Do not restore it or its old task names.

Bootstrap result:

- train 95% CI: $0.05 to $24.85
- independent test 95% CI: -$5.00 to $29.02
- full sample 95% CI: $1.80 to $22.38

Because the independent interval crosses zero, this is supportive shadow
evidence, not a statistically confirmed edge. The latest lifecycle report also
suspends MES for recent decay.

### 9. Other Research Lanes

Current evidence labels matter more than attractive historical statistics:

- QQQ mean reversion: development-only; 136 observations, positive historical
  mean/PF, but failed experiment-wide multiple-test correction. It is
  `research_only`, not paper-review eligible.
- MES reopen drift: retrospective/supportive but independent CI crosses zero and
  recent decay triggered `suspended`.
- Volatility premium: latest lifecycle state `suspended`; lower confidence bound
  not positive and placebo failed.
- Trend participation: collecting, zero resolved observations in the latest
  opportunity-intelligence report.
- Momentum ensemble: `forward_shadow_candidate`; historical component selection
  and survivorship warnings prevent capital authority.
- Confirmed-momentum delayed option entry: rejected after executable ask-to-bid
  replay. The older positive first-mark statistic must not be used as an entry
  edge.
- MES intelligence meta-policy: rejected, negative post-cost expectancy.
- Event-gap continuation: one MRNA +2R causal replay is an unvalidated shadow
  hypothesis. Requires at least 30 resolved candidates across 20 dates and all
  frozen gates.
- GEX reaction: infrastructure and collection only unless current status says
  otherwise. Latest status inspected was blocked.
- Liquidity sweep/MSS/FVG/retest, ORB/PDH, Fibonacci, 1-2-2 reversals, Saty ATR,
  Milkman strategies, bottom reversals, swing momentum, gamma levels, and social
  trader sequences remain candidate families. Each needs a mechanical spec and
  honest tournament; screenshots are not performance evidence.

Authoritative evidence summary:

- `research/VERIFIABLE_EDGE_STATUS_2026-08-17.md`
- `research/OPPORTUNITY_INTELLIGENCE_RESULTS_2026-08-19.md`
- `research/MRNA_EVENT_GAP_AUDIT_2026-08-19.md`
- `research/QUANTMUSE_ADOPTION_AUDIT_2026-08-20.md`

### 10. Opportunity Intelligence and Control Plane

Key paths:

- `scripts/opportunity_intelligence_pipeline.py`
- `data/opportunity_intelligence_report.json`
- `data/opportunity_intelligence_ledger.jsonl`
- `scripts/profitability_control_plane.py`
- `strategies/profitability_control_plane.py`
- `data/profitability_control_plane.json`
- `data/profitability_control_plane_ledger.jsonl`

The pipeline implements regime-aware research allocation, counterfactual gate
attribution, placebo tests, edge-decay monitoring, synchronized block portfolio
simulation, execution-policy proxies, append-only accepted/rejected records,
point-in-time calibration, lower-confidence-bound weighting, and source-health
invariants.

Latest inspected output:

- generated 2026-08-20T21:20:50Z
- all required execution flags false
- research weights: QQQ mean reversion 35%, cash 65%, all other lanes 0%
- these are research weights, never sizes
- lifecycle promotion authority: blocked

Latest profitability control plane:

- action: `hold_cash_collect_counterfactuals`
- selected candidates: none
- execution disabled

## Scheduled Tasks Snapshot

Relevant tasks present and `Ready` at handoff included:

- `Flip-Bot-Entry`, monitors, exploration, and trend entry
- `FlipBotLearningReport` and multiple Flip shadow/evaluation reports
- `IntradayOpportunityRadar`
- `PremarketOpportunityRadar`
- `Opportunity-Intelligence-Pipeline`
- `EventGapContinuationShadow`
- `GEXScanner`
- `MESReopenVixShadowEntry`
- `MESReopenVixShadowExit`
- `VibeTradingOptionsShadowTwin`
- `VibeTradingShadowScanner`
- `VibeTrading-Portfolio-Monitor`
- `Vibe-Trading-Remote-Dashboard`
- `Vibe-Trading-Remote-Dashboard-Fallback`
- `VibeTradingDashboardServer`

`VibeTradingNinjaTraderMESSim` was disabled.

Task existence and `Ready` state do not prove healthy execution. Audit each
task's `LastRunTime`, `LastTaskResult`, action path, log freshness, and output
freshness before claiming it runs correctly.

## Verification Completed for the Latest Cockpit Change

Backend focused tests:

```powershell
python -m pytest agent\tests\test_live_trading_cockpit.py agent\tests\test_intraday_opportunity_radar.py -q
```

Result: 26 passed.

Frontend focused test:

```powershell
Set-Location frontend
npm run test:run -- src/pages/__tests__/TradingCockpit.test.tsx
```

Result: 1 passed.

Frontend build:

```powershell
Set-Location frontend
npm run build
```

Result: passed. Only the existing Vite chunk-size warning remained.

These focused results do not certify the entire dirty worktree. Run broader
suites only after checking environment/runtime cost and do not report old test
counts as current.

## Immediate New-Chat Runbook

Start with observation. Do not edit on the first pass.

```powershell
Set-Location C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
git status --short
git log --oneline -12
```

1. Re-read this handoff and the four authoritative research documents listed
   above.
2. Audit ports 8898/8899 and the remote dashboard supervisor. Repair the remote
   read-only path without weakening authentication or exposing secrets.
3. Probe `/health` and authenticated `/trading/dashboard`; verify schema 5,
   freshness, and execution flags.
4. Run or inspect current premarket/intraday radar and daily-plan outputs. Do not
   show yesterday's setup as today's.
5. Audit Alpaca broker orders, fills, positions, reconciliation, scheduler result
   codes, and decision logs. State exactly whether the bot submitted, filled,
   exited, blocked, or never ran.
6. Audit all shadow ledgers for valid timestamps, duplicate events, unresolved
   outcomes, executable marks, and stale sources.
7. Run the focused dashboard tests above after any dashboard/backend change.
8. Keep order authority unchanged unless the user separately requests a
   promotion and every technical/evidence gate passes.

Useful local health commands:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8898,8899 -ErrorAction SilentlyContinue
Get-ScheduledTask | Where-Object TaskName -Match 'Dashboard|Opportunity|Intraday|Premarket|Flip|MES|Topstep|GEX'
Get-ScheduledTaskInfo -TaskName 'IntradayOpportunityRadar'
Get-ScheduledTaskInfo -TaskName 'Vibe-Trading-Remote-Dashboard'
```

Do not print the contents of:

- `~/.vibe-trading/dashboard-api-key.txt`
- `~/.vibe-trading/remote-dashboard-token.txt`
- broker `.env` files

## Highest-Value Next Work

1. Restore and verify reliable phone access to the read-only dashboard. Add a
   first-class frontend error boundary and a clear source-freshness failure view.
2. Make the premarket-to-intraday pipeline deterministic: discovery, rank,
   completed-bar confirmation, command-card update, alert, outcome resolution,
   and end-of-day review must share stable IDs.
3. Build a daily coverage audit that compares the day's largest causal,
   executable moves against what the radar saw before each move. Separate
   discovery misses, ranking misses, confirmation misses, late alerts, liquidity
   failures, and correct skips.
4. Improve contract selection only with live executable bid/ask/size and an
   explicit max-loss budget. If contract data is missing, keep the underlying
   setup but label the contract pending.
5. Close the feedback loop: every displayed setup, rejected setup, manual choice,
   fill/no-fill, exit, maximum favorable/adverse excursion, and counterfactual
   must resolve into append-only evidence.
6. Reduce duplicated scanners and conflicting reports. Establish one canonical
   opportunity ID, source timestamp, and lifecycle across all dashboard panels.
7. For futures, fix credentials/market recording and collect practice evidence
   before spending on a Combine. Do not bypass the readiness report.
8. For each social strategy, preregister the exact rule before replay. Use
   walk-forward dates, executable costs, winner-removal, parameter-neighborhood,
   regime, and multiple-testing checks.

## Definition of Done for a Dashboard Setup

A setup is useful only when all of these are explicit:

- as-of timestamp and completed-bar timestamp;
- source freshness and completeness;
- symbol and asset class;
- direction and setup family;
- trigger and required confirmation;
- invalidation and defined maximum loss;
- target(s) and reward/risk at the current price;
- current lifecycle: wait, ready for review, no chase, invalid, or stand aside;
- underlying and, where available, an executable contract with bid/ask/size;
- catalyst/event context;
- market/sector/HTF structure;
- liquidity and spread quality;
- supporting and conflicting factors;
- model calibration cohort and sample size;
- evidence label: research, shadow, paper review, or approved;
- no implied guarantee and no hidden order authority.

## Dashboard Blueprint Implementation Update

The React dashboard blueprint Phases A-I was implemented on 2026-08-20 as an
uncommitted, read-only extension. The cockpit contract is now schema 6 and adds
freshness-labeled retro, journal, social, catalyst, and provenance-gated options
context. Auth-gated Alpaca IEX quote and bar readers support the ticker,
watchlist, and chart drawer. The React app adds persistent watchlist/risk
preferences, position sizing, blocker explanations, Retro and Journal pages,
options/social context panels, hotkeys, and focused tests. Execution authority
remains hardcoded off.

Phase H decision: **deprecate the legacy static HTML dashboard**. The audited
`VibeTradingDashboardServer` task launches the live API server on port 8899; it
does not regenerate static HTML. At audit time its state was `Ready`, its last
run was 2026-08-20 07:20:59 local, and its last result was `-1`, while port 8899
was listening. The legacy `~/.vibe-trading/dashboard.html` file was last written
2026-07-28 22:51:44 local. The file and task were left in place, no scheduled
task registration was changed, and no React navigation link to the stale report
was added. The dashboard task was subsequently restarted through its existing
registration to deploy schema 6; live dashboard, quote, and bar probes passed.

## Paste-Ready Prompt for the New Chat

```text
Open and read:
C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\CODEx_CLAUDE_COLLAB\CODEX_NEW_CHAT_HANDOFF_FULL_TRADING_SYSTEM_2026-08-20.md

Then inspect the current Vibe-Trading worktree before changing anything. The
working tree is heavily dirty and contains substantial uncommitted dashboard,
research, scheduler, test, and generated-data work. Do not reset, clean, revert,
or overwrite unrelated changes.

Begin with an operational and evidence audit:
1. Verify the local dashboard backend and repair the authenticated read-only
   phone gateway/tunnel if it is unhealthy.
2. Verify current dashboard source freshness and the schema-6 command card.
3. Reconcile today's Alpaca orders, fills, positions, exits, task results, and
   decision logs. Do not infer a trade from scheduler state.
4. Evaluate all shadow ledgers and report current, source-grounded counts and
   lifecycle states.
5. Preserve all safety boundaries and keep execution authority unchanged.

Primary product direction: dashboard-first manual decision support, with bots
and shadow loggers continuing to collect causal executable evidence. Improve the
system end to end, but do not claim guaranteed profitability, fabricate levels
or probabilities, tune negative tests into positive claims, or promote social
setups without frozen forward validation.
```

## Final Handoff Principle

The system's advantage should come from better discovery, causal timing,
execution realism, disciplined abstention, and a closed evidence loop. More
indicators or stronger language do not create edge. The next chat should make
the current system more reliable and measurable before making it more
aggressive.
