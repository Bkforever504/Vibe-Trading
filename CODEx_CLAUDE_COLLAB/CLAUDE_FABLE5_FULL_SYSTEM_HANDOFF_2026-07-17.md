# Claude Fable 5 Full Trading System Handoff

Date: 2026-07-17 CT  
Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`  
Runtime state: `C:\Users\kenne\.vibe-trading`  
Purpose: Give Claude Fable 5 a complete, safety-preserving map of the bots, strategy logic, shadow research, learning loop, state, reports, automation, and current evidence.

## 1. Start Here

Open the entire repository root, not an individual file:

```text
C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
```

Use this handoff as the current orientation document. Do not assume older prose files are current. `CLAUDE.md`, `STATUS.md`, `KNOWLEDGE/HANDOFF.md`, and earlier files in `CODEx_CLAUDE_COLLAB` contain valuable history but can describe older metrics or incidents that have since been repaired.

Truth precedence:

1. Current broker read-only reconciliation and current generated JSON reports.
2. Durable state in `C:\Users\kenne\.vibe-trading`.
3. Current source code and tests.
4. Signal registry, immutable trial ledger, promotion rules, and append-only logs.
5. This handoff.
6. Older handoffs and narrative status documents.

Never print, copy, commit, or place credentials in a handoff. Environment variable names are documented below, but values must stay secret.

## 2. Non-Negotiable Safety Boundaries

- Do not enable funded/live execution while auditing or improving the system.
- Do not weaken the kill switch, execution guard, liquidity checks, daily-loss limits, position reconciliation, contract limits, or state integrity.
- Do not route around Polymarket's US geoblock.
- Do not convert social-media screenshots, trader claims, hypothetical peaks, reconstructed telemetry, or same-day clustered shadow episodes into proof of profitability.
- Do not auto-promote a symbol, strategy, gate, sizing rule, or exit policy. Promotion requires preregistered forward/OOS evidence and human approval.
- Preserve maker/checker separation. Research proposes; independent reports grade; a human approves.
- Preserve observed-versus-backfilled provenance. Synthetic legacy telemetry must never inflate forward-complete counts.
- Preserve atomic/locked state writes and audit trails.
- A hard block is appropriate for kill switch, dirty reconciliation, invalid/stale liquidity, broker/order integrity, or a documented safety limit. Alpha/context modules are advisory unless point-in-time counterfactual evidence earns veto authority.
- Do not use hindsight fields in live decisions or forward labels.

Current global posture: evidence-building and paper/read-only governance. A generated report showing `execution_enabled=false` or `can_submit_orders=false` is intentional.

## 3. Complete Repository Map

All project folders are under the repository root:

| Folder | Purpose |
|---|---|
| `.devcontainer` | Development container configuration. |
| `.github` | GitHub workflow and repository automation. |
| `.venv` | Local Python environment; do not treat as source. |
| `agent` | Core package, factors, adapters, shared utilities, tests, and historical framework modules. |
| `agent/tests` | Primary automated test suite; roughly 630 test files at this snapshot. |
| `assets` | Static assets used by reports/dashboard. |
| `CODEx_CLAUDE_COLLAB` | Cross-agent decisions, handoffs, audits, build briefs, and task history. Read recent files first. |
| `data` | Append-only observations, shadow lifecycles, outcomes, postmortems, decisions, and experiment data. |
| `docs` | Project documentation. |
| `examples` | Example configurations and workflows. |
| `frontend` | Dashboard/frontend source and dependencies. |
| `KNOWLEDGE` | Durable agent memory, playbooks, prop research, and skills. |
| `research` | Registries, immutable trials, research datasets, third-party study areas, and strategy labs. |
| `rules` | Promotion/governance and operating rules. |
| `scripts` | Scanners, analytics, report generators, automation runners, audits, and PowerShell task entry points. |
| `strategies` | Execution, paper, shadow, prediction-market, options, prop, and portfolio strategy modules. |
| `tools` | Imported/probed open-source systems and integration research. |
| `wiki` | Additional project knowledge. |

Snapshot size at handoff creation:

- `strategies`: 84 files.
- `scripts`: 438 files.
- `agent`: 2,436 files.
- `agent/tests`: 630 files.
- `data`: 102 files.
- `research`: 2,228 files.
- `CODEx_CLAUDE_COLLAB`: 162 handoff/history files before this file.
- `tools`: large vendored/probe tree; do not edit dependency output casually.

The companion manifest beside this handoff enumerates every project file included in the handoff scope:

```text
C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\CODEx_CLAUDE_COLLAB\CLAUDE_FABLE5_FULL_SYSTEM_FILE_MANIFEST_2026-07-17.txt
```

Regenerate it when needed:

```powershell
rg --files strategies scripts agent data research rules tools examples CODEx_CLAUDE_COLLAB KNOWLEDGE docs frontend assets wiki | Sort-Object
```

## 4. Durable Runtime State and Logs

Runtime root:

```text
C:\Users\kenne\.vibe-trading
```

Key durable files:

- `flip-trades.json`: actual Flip paper trade state and realized outcomes.
- `flip-trades.json.bak`: backup state.
- `options-trades.json`: options-bot grouped trade state.
- `options-trades.backup-2026-07-10-pre-repair.json`: preserved pre-repair backup.
- `kalshi-weather-paper-state.json`: Kalshi weather paper positions and closures.
- `polymarket-weather-paper-state.json`: historical Polymarket weather paper state.
- `guard-blocks.jsonl`: execution-guard blocks.
- `kalshi-guard-blocks.jsonl`: Kalshi guard blocks.
- `copy-trader-profiles.json` and related signal files: tracked trader intelligence.
- `social-arb-observations.json`: social-arbitrage observations.
- `sessions.db`: durable session database.
- `dashboard.html`: generated dashboard.
- `reports\`: authoritative generated reports.
- `logs\`: scheduled-run and bot logs.

Do not rewrite durable JSON by hand. Use the owning module's atomic/locked write path and preserve backups/audit metadata.

## 5. Current Verified System State

These values were rechecked on the host during this handoff. Re-run the verification block before relying on them later.

### Safety and integrity

- Options reconciliation: `status=ok`, exact signed book, `entries_allowed=true`, no unexplained residual, no missing or netted legs.
- Active broker groups: two. One IWM iron condor is `exit_pending`; one PLTR put spread is open.
- Risk fail-closed proof: 4/4 deterministic cases pass.
- Execution-gate audit: pass, 100 registered signals, 0 issues, 1 read-only broker-client warning for the concentration monitor.
- Market schedule alignment: 55/55 aligned, 0 issues, 2 benign extra-start warnings.
- Signal-stack health: 61 OK, 1 stale, 0 missing, 0 error. The stale item is the intentionally disabled Polymarket weather task after the US venue decision.
- Scheduled tasks under `\VibeTrade\`: 72 total, 71 Ready, 1 Disabled. Root tasks also include `\Flip-Bot-Monitor` and `\IWM-Bot-Monitor`.

### Elite scorecard

Current report: `C:\Users\kenne\.vibe-trading\reports\elite-bot-readiness-scorecard.json`

- Overall: 6.3/10, evidence-building.
- Operational integrity: 5/10 because the disabled Polymarket item is counted stale.
- Risk controls: 10/10.
- Entry quality: 7/10.
- Daily universe selection: 5/10.
- Exit quality: 4/10.
- Learning loop: 8/10.
- Research validity: 6/10.
- Proven profitability: 4/10.
- Autonomous safety: 8/10.

The score is evidence-capped and is not a promise of daily profit.

### Flip realized paper performance

Current report: `C:\Users\kenne\.vibe-trading\reports\flip-equity-curve.json`

- 12 post-hardening closed trades; 1 pre-hardening trade excluded.
- Net realized P&L: +$2,332.
- 8 wins, 4 losses; 66.67% win rate.
- Gross profit: $2,923; gross loss: $591.
- Profit factor: 4.9459.
- Expectancy: +$194.33 per trade.
- Peak cumulative realized P&L: $2,923.
- Maximum/current drawdown: -$591, or -20.22% of peak cumulative realized profit.
- The report is zero-start realized P&L, not account-equity drawdown.
- The two latest trades, 2026-07-16 and 2026-07-17, were losses. The bot is still in drawdown.

Earlier 10-trade figures such as 80% win rate and 7.59 profit factor are stale. Do not use them as the current baseline.

### Broad accelerated Flip shadow evidence

Current report: `C:\Users\kenne\.vibe-trading\reports\flip-shadow-pnl-evaluator.json`

- 294 accelerated completed episodes, 314 total completed paths in the broader evaluator snapshot.
- Accelerated win rate: about 34.7%.
- Accelerated expectancy: about -7.46% per executable-quote episode; the broader current evaluator is also negative.
- Average capture efficiency: about 0.219.
- Average giveback: about 32.47%.
- Same-day clustered shadow episodes accelerate failure discovery but do not create independent trading-day evidence.
- No challenger is promotion eligible.
- QQQ has a small positive sampled/OOS expectancy in the current report, but it lacks the required trade-day and total-sample evidence. It remains shadow/paper only.
- Hypothetical peak P&L is not realizable performance and must never be reported as bot profit.

The broad shadow setup is currently negative. This is the central research fact, even when individual social-media screenshots show large winners.

### Exit telemetry

- `flip-exit-quality.json`: 13 closed, only 2 complete by that report's criteria.
- `flip-path-telemetry-completeness.json`: 13 closed, 2 observed complete forward paths, and 11 pre-infrastructure legacy paths correctly excluded as synthetic/incomplete.
- The prior 2-versus-1 discrepancy was stale report timing. Regeneration now gives 2 complete in both reports.
- Exit-quality promotion requires at least 50 genuine forward-complete paths.
- Structural exit challengers currently have zero complete forward tournament paths and must accumulate observations.

### Kalshi weather paper evidence

Current reports:

```text
C:\Users\kenne\.vibe-trading\reports\kalshi-weather-bot.json
C:\Users\kenne\.vibe-trading\reports\kalshi-weather-bot-performance.json
C:\Users\kenne\.vibe-trading\reports\kalshi-weather-live-readiness.json
```

- Paper only; live readiness is false.
- 12 closed positions, 7 winners, 58.33% win rate.
- Net paper P&L: +$0.71.
- Profit factor: 1.423.
- Expectancy: +$0.0592 per closure.
- Maximum drawdown: $1.22.
- 19 open positions and 12 city-days in the latest performance snapshot.
- Blockers include insufficient promotion closures/dates, weak calibration, failure to beat market calibration, and an unaudited authenticated order adapter.

## 6. Core Strategy Source Files

Primary strategy modules in `strategies`:

```text
backtest.py
catalyst_scanner.py
copy_trader_watchlist.py
czt_order_flow.py
execution_guard.py
flip_bot.py
flip_contract_ranker.py
flip_day_type_router.py
flip_live_readiness.py
flip_retest_quality.py
flip_scanner.py
flip_shadow_setup_challengers.py
ironbeam_market_data.py
iwm_options_bot.py
kalshi_history_fetcher.py
kalshi_prediction_bot.py
kalshi_profile_scraper.py
kalshi_weather_bot.py
kalshi_weather_execution.py
options_state.py
pnl_tracker.py
polymarket_fed_whale_watch.py
polymarket_wallet_tracker.py
polymarket_weather_bot.py
portfolio_guard.py
portfolio_monitor.py
prop_rule_gate.py
risk_kill_switch.py
shadow_ai_signals.py
shadow_consensus.py
shadow_pullback_signal.py
social_arbitrage_watchlist.py
spy_noise_area.py
strat_30m_continuation.py
topstep_prop_bot.py
topstep_replay_backtester.py
trade_history_importer.py
trading_dashboard.py
tradovate_market_data.py
```

Read every file in `strategies`, not only this selected list. The manifest contains the remainder.

## 7. Flip Bot: Current Execution and Research Logic

Primary file: `strategies\flip_bot.py`

Supporting modules:

- `strategies\flip_day_type_router.py`
- `strategies\flip_retest_quality.py`
- `strategies\flip_contract_ranker.py`
- `strategies\flip_shadow_setup_challengers.py`
- `strategies\shadow_consensus.py`
- `strategies\execution_guard.py`
- `strategies\risk_kill_switch.py`
- `strategies\portfolio_guard.py`
- `scripts\point_in_time_quotes.py`
- all Flip analytics/report scripts listed later.

### Current execution posture

- Alpaca paper endpoint is the default development lane.
- Funded/live execution requires explicit flags and approval acknowledgements. Do not set them during research.
- Primary execution symbol defaults to SPY.
- Paper challenger symbols are configured separately and capped at one contract.
- Default scan universe includes TSLA, NVDA, AAPL, META, AMZN, AMD, PLTR, and COIN.
- Accelerated shadow candidates include SPY, QQQ, IWM, NVDA, TSLA, AAPL, GOOGL, and META, with additional allowlisted names including HOOD, RIVN, NFLX, and COIN.

### Risk and execution constants

- Maximum risk per trade: 2%.
- Maximum contracts per order: 5.
- Maximum open Flip positions: 2.
- Maximum spread: 10 cents by default.
- Slippage assumption: 3%.
- Profit target: +75% contract return.
- Stop: -30% contract return.
- Ratchet arms at +40% with a +25% floor.
- Base maximum giveback: 15 percentage points.
- Tier: at +50% best return, floor becomes +35%.
- Tier: at +60% best return, floor becomes +45%.
- The scheduled monitor first performs a protective pass, runs the intraday entry scan, then uses `--protect-loop` to rescan open or exit-pending positions every 60 seconds for up to 12 minutes. Task Scheduler uses `MultipleInstances=IgnoreNew`.
- Exit acceptance is not treated as a fill. Pending close orders remain open and protected, duplicate close submissions are suppressed, and realized exit price/P&L use the broker's `filled_avg_price` after `status=filled`.
- A confirmed full single-leg entry immediately places a DAY limit sell at the +75% target. Unconfirmed/estimated entries and multi-leg spreads do not receive resting targets.
- Stops, ratchets, time exits, structural exits, and close-all cancel the resting target and confirm cancellation before submitting a competing sell. If the target fills during cancellation, it is recorded as the exit and no second sell is sent.
- The manual-reset kill switch blocks new buys but cannot block risk-reducing sell-to-close orders.
- Same-day re-entry controls and a daily realized-loss guard run through the shared execution guard.
- Point-in-time quotes, quote age, spread, entry ask, monitoring marks, exit bid, fill provenance, and P&L extremes are recorded when available.

### Live/paper setup families

- VWAP/50EMA bull trend calls.
- VWAP/50EMA bear trend puts.
- Five-minute ORB and break/retest logic.
- Gap/catalyst and breakout research lanes.
- Earnings and high-momentum research lanes.
- SPY noise-area paper lane, one contract.
- Paper challenger lane, one contract.

### ORB and retest logic

- Five-minute opening range.
- Breakout/retest observation window: 60 minutes.
- Maximum retest age: 15 bars.
- Retest tolerance: approximately 10% of opening-range width.
- Extension beyond 1.5 opening-range widths is recorded/rejected for the strict retest research setup.
- Break and retest is explicitly factored into the current telemetry and research scorer.
- `flip_retest_quality.py` grades retests A/B/C/rejected using extension, timing, volume, VWAP, EMA, and confirmation context.
- Research-backed filters must remain setup-specific. A filter trained for bullish continuation must not veto a bearish reversal setup.

### Newly built point-in-time intelligence

- `flip_day_type_router.py`: 10:00 ET advisory classifier for trend, range, failed extension, or unknown. Uses only available bars and a short-window ADX implementation. It does not veto live entries.
- `flip_retest_quality.py`: grades retest quality and records rejection reasons.
- `flip_contract_ranker.py`: research ranking of delta, spread, quote age, expected-move room, and premium expansion. It does not silently replace actual contract selection.
- `flip_shadow_setup_challengers.py`: independent forward lanes for 15-minute ORB retest, significant-level sweep reversal, extension reversal, weakening-signal exits, and an exit tournament.
- Exit tournament: current percentage ratchet versus VWAP structural trail versus prior five-minute-bar trail. Forward-only; no live change until preregistered evidence exists.
- Expected-move features: ATM IV implied move, opening-range fraction, expected-move consumption, breakout overshoot, and point-in-time provenance.
- ATR feature: breakout-candle ATR ratio.
- Other logged context includes ORB direction, VWAP/EMA state, breadth, TTM state, GEX provenance, market force, catalysts, relative volume, liquidity, and quote freshness.

### Gate-authority repair status

The setup-agnostic gate mismatch was repaired with authority boundaries, decay-aware watchdog logic, and invariant tests. The watchdog still retains 41 historical cases, but their latest timestamp is 2026-07-15 and severity now decays with business-day age. Its current status is `watch`, not a fresh high-severity regression. GOOGL and QQQ positive-shadow suppression remain review items, not proof that a gate is wrong.

Historical root cause: research/context modules accumulated as independent vetoes inside `shadow_consensus.py`. Some advisory signals were granted authority to kill setup types they did not model. A bullish advisory blocking a bearish put is logically invalid.

Fable 5 continuing assignment:

1. Trace `shadow_entry_advice`, `PRIMARY_STAND_ASIDE_BLOCKERS`, and every consensus blocker by setup family and direction.
2. Prove whether each blocker is safety-authoritative or alpha-advisory.
3. Produce point-in-time counterfactual results by blocker, setup, direction, day type, and symbol.
4. Repair only newly observed, demonstrably setup-agnostic or contradictory vetoes.
5. Do not broadly loosen liquidity, reconciliation, loss, or kill-switch gates.
6. Add regression tests ensuring advisory modules cannot veto unrelated setup families.

## 8. Defined-Risk Options Bot

Primary file: `strategies\iwm_options_bot.py`

State/reconciliation:

- `strategies\options_state.py`
- `scripts\options_position_reconciler.py`
- `strategies\execution_guard.py`
- `strategies\portfolio_guard.py`
- `strategies\portfolio_monitor.py`
- `strategies\risk_kill_switch.py`

Strategy families:

- Iron condor: roughly 30-45 DTE, approximately 16-delta short strikes, $2 default wings, 50% profit target.
- Put credit spread: roughly 7-14 DTE, approximately 0.25-delta short leg, $3 default or $5 configured width, 50% profit target.
- Wheel/cash-secured put lane: roughly 21-35 DTE, approximately 0.30 delta.

Configured symbol/strategy map includes:

- IWM: iron condor and put spread.
- SPY: put spread.
- QQQ: put spread.
- TSLA: iron condor and put spread.
- NVDA: put spread and wheel.
- AAPL: put spread and wheel.
- PLTR: put spread.

Risk controls:

- Maximum risk per trade: 2%.
- Maximum open groups: 8.
- Maximum new trades per day: 5.
- Maximum contracts per order: 5.
- Daily loss limit: 3%.
- Maximum spread threshold: 35%.
- Confidence threshold: 8 in paper, 9+ for any future live lane.

Integrity logic already built:

- Signed-quantity reconciliation of durable groups against broker positions.
- Entry fail-closed on missing legs, unexplained residuals, duplicate active legs, or closed groups still open.
- Atomic locked writes and backup/audit history.
- Time-separated flat confirmation to prevent one transient empty broker response from closing all tracked groups.
- Per-leg side recording.
- Quote-based marking for netted/overlapping legs.
- Per-order-ID P&L de-duplication.
- Read-only approval-gated repair plans.

Do not infer exact strategy P&L from account cash flow. `pnl_tracker.py --days 30` can show broker account/equity and order cash flow, but raw cash flow is not matched strategy profit. Use grouped trade state and reconciled closures.

## 9. Kalshi Weather Bot and Prediction Markets

Primary Kalshi files:

- `strategies\kalshi_weather_bot.py`
- `strategies\kalshi_weather_execution.py`
- `strategies\kalshi_history_fetcher.py`
- `strategies\kalshi_prediction_bot.py`
- `strategies\kalshi_profile_scraper.py`

Weather logic:

- Venue-specific Kalshi contract parsing and ASOS station mapping.
- Forecasts query station coordinates, not generic city centers.
- Three independent model families: GFS, ECMWF, and ICON.
- Minimum ensemble-member requirement: 20.
- Agreement required across all three model families.
- Minimum model-versus-market edge: 10% during validation.
- Maximum market spread: 10%.
- Minimum time to settlement: 2 hours.
- Maximum one contract per paper position in the current cautious lane.
- Maximum $15 new daily paper risk.
- Maximum 20 open positions.
- Temperature ladder research, asymmetric 2-8 cent candidate reporting, Kelly-fraction telemetry, calibration scoring, and city/lead-time performance.
- Authenticated execution remains disabled until the adapter, signing, jurisdiction, reconciliation, calibration, and promotion evidence are reviewed.

Polymarket files remain for research/history:

- `strategies\polymarket_weather_bot.py`
- `strategies\polymarket_wallet_tracker.py`
- `strategies\polymarket_fed_whale_watch.py`

The Polymarket scheduled weather bot is intentionally disabled because US access is blocked. Do not evade that restriction. The legal live target is Kalshi.

## 10. Prop/Futures and Other Strategy Systems

Prop/futures modules and research are still part of the repository:

- `strategies\topstep_prop_bot.py`
- `strategies\topstep_replay_backtester.py`
- `strategies\prop_rule_gate.py`
- `strategies\tradovate_market_data.py`
- `strategies\ironbeam_market_data.py`
- NQ/MNQ replay, sweep, partial-exit, VIX-filter, consistency, and OOS documents in `CODEx_CLAUDE_COLLAB`.
- Durable playbooks in `KNOWLEDGE\PROP_FIRM_AUTOMATION_BLUEPRINT.md` and `KNOWLEDGE\TOPSTEP_PROP_BOT_PLAYBOOK.md`.

These are separate from the Alpaca options bots. Do not mix prop-firm rule logic into Flip execution without an explicit adapter and test boundary.

## 11. Complete Shadow, Context, and Research Stack

The full list lives in `scripts`, `strategies`, `data`, `research`, and the companion manifest. Major families include:

### Flip outcome and learning analytics

- Accelerated bot learning and compounding reports.
- Adaptive options shadow playbook.
- Closed-trade postmortem and daily outcome reviewer.
- Bot behavior regression watchdog.
- Elite readiness scorecard.
- Execution-gate audit and risk fail-closed proof.
- Flip equity curve, exit quality, exit taxonomy, exit-policy comparison, and feature ablation.
- Flip learning report, missed-banger review, rejected-trade intelligence, and outcome science.
- Flip live readiness, path telemetry completeness, decision attribution, signal grades, leaderboards, time buckets, and shadow P&L evaluator.
- Loop closure, loop readiness, self-improving strategy verifier, and immutable edge-trial ledger.

### Market and options context

- Candlestick and higher-timeframe scanners.
- Cheap-asymmetry scanner.
- Crowded-positioning context.
- CZT volume-profile/order-flow context: value area high/low, point of control, VWAP, acceptance, aggression, absorption, and resting-liquidity concepts.
- Deep-liquid universe scanner and daily options universe ranker.
- Distribution, HMM, Hurst, PCA, and regime research.
- GEX scanner, with GEX advisory only; never a directional oracle.
- Implied-versus-realized volatility and IV-rank context.
- Market breadth, opening-range breadth, market force, catalysts, and market schedule.
- MoonDev liquidation and public-social context.
- Options surface intelligence, liquidity feasibility, expected move, and premium-level telemetry.
- Premarket EMA, relative volume, SEC insider context, sector rotation, weekly hot instruments, and social trend scanners.

### Indicator shadow loggers

Append-only shadow logs include KAMA, MFI, momentum, QQQ/GLD, RSI(2), SMC, TTM squeeze, WaveTrend, Williams %R, Strat 30-minute continuation, premarket EMA, and additional registered signals.

Representative data files:

```text
data\flip_shadow_candidates_log.jsonl
data\closed_trade_postmortem_log.jsonl
data\kama_shadow_log.jsonl
data\mfi_shadow_log.jsonl
data\momentum_shadow_log.jsonl
data\qqq_gld_shadow_log.jsonl
data\rsi2_shadow_log.jsonl
data\williams_r_shadow_log.jsonl
```

Enumerate every logger rather than assuming this representative list is exhaustive:

```powershell
rg --files data | Sort-Object
rg -n "jsonl|shadow|observation|decision" scripts strategies
```

## 12. Learning Loop and Governance

The system does have a self-improving loop, but it is intentionally governed rather than self-authorizing:

1. Scanners produce point-in-time candidates and decision/skip reasons.
2. Shadow lanes create simulated lifecycles with executable quote assumptions.
3. Monitors record path marks, best/worst P&L, quote age, spread, context, and exit counterfactuals.
4. Closed outcomes are joined to entry reasoning and classified by reason, setup, regime, symbol, and time bucket.
5. Postmortems nominate a hypothesis; they do not rewrite production code.
6. A trial is preregistered in the immutable ledger with a frozen rule, sample requirement, and evaluation metric.
7. Maker and checker remain separate.
8. OOS/forward evidence is graded.
9. Passing candidates become human-review candidates only.
10. A human must approve any live/paper promotion or threshold change.

Governance sources:

- `research\signal_registry.json`
- `research\edge_trials\`
- `rules\signal_promotion_rules.md`
- `LOOP.md`
- `CODEx_CLAUDE_COLLAB\DECISIONS.md`
- `CODEx_CLAUDE_COLLAB\TASK_QUEUE.md`
- `KNOWLEDGE\VIBE_TRADING_AGENT_MEMORY.md`

Current loop state: approximately 100 registered loops, mostly L1/L2 evidence collection, no L3 self-authorizing production loop. The verifier tracks about 59 instruments, has zero promotion-ready candidates, governance passes, and human review remains required.

## 13. Authoritative Report Directory

Read all JSON files in:

```text
C:\Users\kenne\.vibe-trading\reports
```

High-priority reports:

```text
accelerated-bot-learning.json
bot-behavior-regression-watchdog.json
daily-options-universe-ranker.json
deep-liquid-universe-scan.json
edge-trial-ledger.json
elite-bot-readiness-scorecard.json
execution-gate-audit.json
flip-bot-learning-report.json
flip-decision-missed-banger-review.json
flip-equity-curve.json
flip-execution-challengers.json
flip-exit-policy-comparison.json
flip-exit-quality.json
flip-feature-ablation.json
flip-live-readiness.json
flip-path-telemetry-completeness.json
flip-shadow-pnl-evaluator.json
kalshi-weather-bot.json
kalshi-weather-bot-performance.json
kalshi-weather-live-readiness.json
loop-closure-report.json
loop-readiness-audit.json
market-schedule-alignment.json
option-premium-levels.json
options-liquidity-feasibility.json
options-position-reconciliation.json
options-surface-intelligence.json
outcome-science-report.json
portfolio-concentration.json
risk-fail-closed-proof.json
self-improving-strategy-verifier.json
signal-stack-health.json
```

Do not stop at this selected list. Enumerate all reports:

```powershell
Get-ChildItem -LiteralPath 'C:\Users\kenne\.vibe-trading\reports' -File | Sort-Object Name
```

## 14. Scheduled Automation

Inspect all VibeTrade tasks:

```powershell
Get-ScheduledTask -TaskPath '\VibeTrade\' | Sort-Object TaskName | Format-Table TaskName,State
Get-ScheduledTask | Where-Object { $_.TaskName -in @('Flip-Bot-Monitor','IWM-Bot-Monitor') } | Format-Table TaskPath,TaskName,State
```

Task actions generally call `scripts\run_*.ps1`. Read each runner and its log target before changing schedules.

The disabled Polymarket weather task is intentional. Do not mark it unhealthy by re-enabling an unavailable venue. Prefer teaching the health report that the retirement/venue migration is expected.

## 15. Open-Source and External Research Assets

Top-level probe/import directories:

- `tools\investing_algorithm_framework_probe`
- `tools\pmxt-probe`
- `tools\tradingview-mcp`
- `research\pine_strategy_lab`
- all additional projects under `research` and the manifest.

These repositories are research inputs, not trusted production execution code. Preserve the AST/safety checker in `research\strategy_adapter_safety.py`. It blocks dangerous dynamic imports and process/network/system access patterns. Imported logic must be reduced to a testable, vendor-neutral idea and evaluated through the normal shadow/OOS path.

Notable prior research includes Kronos forecasting, TensorTrade/self-improving agents, TradingView MCP, PMXT, OpenAlice, Mahoraga, MoonDev, Pine strategies, market-force/regime models, SPY/0DTE research, and public-social research. Search `CODEx_CLAUDE_COLLAB` for the corresponding audit before reusing any idea.

## 16. Broker Plan

Current broker-development lane: Alpaca paper.

Funded Flip broker research is documented in:

```text
CODEx_CLAUDE_COLLAB\CODEX_HANDOFF_2026-07-16_FLIP_BOT_BROKER_SELECTION.md
```

Priority at that review:

1. Webull OpenAPI if access, credential rotation, option quote quality, sandbox behavior, order preview, closing, and reconciliation all pass.
2. Tradier Pro.
3. Tradier Lite.

Robinhood's available MCP path was read-only and not sufficient for autonomous order execution. Webull MCP is also read-only; actual execution requires direct OpenAPI integration. Build a broker-neutral adapter for quote, chain, preview, buy-to-open, close, positions, orders, and buying power. Credential expiry/rotation must alert before the market opens.

No funded broker switch is approved merely by this handoff.

## 17. Environment Variables and Secrets

Possible environment/config sources include the user environment and `agent\.env`. Never print their values.

Important variable names include:

```text
ALPACA_API_KEY
ALPACA_SECRET_KEY
ALPACA_PAPER
ALPACA_BASE_URL
FLIP_LIVE_EXECUTION_ENABLED
FLIP_LIVE_APPROVAL_ACK
OPTIONS_LIVE_EXECUTION_ENABLED
KALSHI_API_KEY_ID
KALSHI_PRIVATE_KEY_PATH
KALSHI_ENABLE_LIVE_TRADING
KALSHI_LIVE_APPROVAL_ACK
DISCORD_WEBHOOK_URL
```

There are additional strategy, risk, path, quote, and broker variables. Discover names without values:

```powershell
rg -o --no-filename "(?:os\.getenv|os\.environ\.get)\([\"'][A-Z0-9_]+" strategies scripts agent | Sort-Object -Unique
```

## 18. P0 and P1 Work Queue for Fable 5

### P1: Gate-authority regression watch

The authority repair is complete. Confirm no new mismatch timestamps appear after 2026-07-15, review GOOGL/QQQ suppression with point-in-time counterfactual evidence, and do not broadly remove safety gates.

### P0: Preserve exact position integrity

Re-run reconciliation before and after any options change. Do not modify durable state unless an approval-gated repair plan proves a mismatch and a backup is created.

### P1: Exit-path evidence

Ensure every newly opened Flip trade initializes and persists path telemetry at entry, records monitor marks through restarts, and produces one observed forward-complete path at closure. The prior report discrepancy is resolved and both post-infrastructure closures are observed-complete. Continue accumulating toward 50 forward paths and verify Monday's actual broker-filled exits land materially closer to the designed stop/ratchet floors.

### P1: Ranked setup/day-type evaluation

Use the day-type router and retest scorer as advisory/ranking research. Compare strict break/retest, continuation, range reversal, and failed-extension paths. Keep setup identity in every result.

### P1: Contract selection evidence

Continue the contract-ranker tournament on ATM/slightly ITM candidates using real bid/ask, delta, spread, quote age, and expected-move room. Do not select deep OTM contracts from screenshot returns.

### P1: Kalshi weather calibration

Accumulate closures across independent city-days, compare model Brier/calibration against market calibration, audit station/settlement mappings, and finish an authenticated read/preview adapter before considering a one-contract live canary.

## 19. Exact Recheck Block

Run from the repository root in PowerShell. These commands are intended to be read-only unless a script's own help explicitly says otherwise.

```powershell
Set-Location 'C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading'

python scripts/options_position_reconciler.py --print
python scripts/risk_fail_closed_proof.py --print
python scripts/execution_gate_audit.py --print
python scripts/market_schedule_alignment.py --print
python scripts/signal_stack_health_report.py
python scripts/elite_bot_readiness_scorecard.py --print

python scripts/flip_equity_curve_report.py --print
python scripts/flip_shadow_pnl_evaluator.py --print
python scripts/flip_path_telemetry_completeness.py --print
python scripts/flip_exit_quality_report.py --print
python scripts/bot_behavior_regression_watchdog.py --print
python scripts/self_improving_strategy_verifier.py --print
python scripts/accelerated_bot_learning_report.py --print

python strategies/kalshi_weather_bot.py --print
python scripts/kalshi_weather_performance_report.py --print
python scripts/kalshi_weather_readiness.py --print

Get-ScheduledTask -TaskPath '\VibeTrade\' | Sort-Object TaskName | Format-Table TaskName,State
git status --short
```

Some filenames/CLI flags can evolve. If a command name differs, locate its current equivalent with:

```powershell
rg --files scripts | rg 'reconcil|fail_closed|gate_audit|schedule|health|scorecard|equity|shadow_pnl|path_telemetry|exit_quality|watchdog|self_improving|accelerated|kalshi_weather'
python <script> --help
```

Current host verification passes 197 Flip-focused tests, including 80 monitor/entry-quality tests, pending-entry reconciliation, partial-fill sizing, pending-fill exit handling, and resting-target race coverage. Compilation and PowerShell parsing pass. The execution audit and 4-case risk proof also passed. Do not claim the entire repository suite is current unless you run it on this Windows host.

## 20. Working Tree Warning

The repository is dirty with user, Codex, Claude, generated-log, and research changes. Do not reset, checkout, clean, or revert broadly. Inspect `git status --short`, understand ownership, and work with existing changes.

Do not commit generated runtime state or secrets. Do not overwrite append-only logs. Scope commits narrowly if the user requests one.

## 21. Definition of a Successful Fable 5 Pass

A successful pass does not claim that the bots are perfect or that exponential returns are guaranteed. It should:

1. Reproduce the current integrity and performance reports.
2. Explain any discrepancy before changing behavior.
3. Keep the setup-authority repair from regressing without weakening safety.
4. Add focused regression tests.
5. Preserve paper/live boundaries.
6. Improve forward telemetry completeness.
7. Register any new hypothesis before evaluating it.
8. Leave exact commands, artifacts, and evidence for the next agent.

The system has substantial infrastructure and a positive small-sample realized Flip record, but its broad shadow expectancy is currently negative, exit evidence is sparse, and no challenger has earned promotion. The next competitive jump comes from correcting decision authority, improving setup-specific selection, and collecting honest forward paths, not from adding another unproven veto or copying a social-media result.
