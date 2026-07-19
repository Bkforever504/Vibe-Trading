# Claude Fable 5 Handoff - Major Trading Bot Upgrades

Date: 2026-07-10
Owner: Kenny
Primary workspace: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Dashboard: `C:\Users\kenne\.vibe-trading\dashboard.html`

## Mission

Perform a senior-level audit and major upgrade pass across every important trading-system layer:

- instrument selection
- entry quality and timing
- exit quality and profit capture
- position sizing and portfolio risk
- broker/order reconciliation
- options liquidity and fill realism
- market data freshness and provenance
- shadow experimentation and learning
- strategy validation and backtesting
- scheduling, health, alerts, and recovery
- dashboards, postmortems, and daily accountability

Implement improvements directly in the repo, add focused tests, regenerate reports, and leave a precise handoff. Do not stop at recommendations when a safe code improvement can be completed and verified.

"Major upgrades" does not mean more indicators, more trades, or looser risk. It means stronger evidence, cleaner state, fewer false signals, better execution discipline, and faster learning from every trade and skip.

## Start Here

Before editing, read these files completely:

1. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\CLAUDE.md`
2. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\STATUS.md`
3. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\CODEx_CLAUDE_COLLAB\NEW_CHAT_HANDOFF_2026-07-07_DAILY_EDGE_AND_MARKET_MASTERY.md`
4. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\KNOWLEDGE\skills\vibe-trading-safety-gates.md`
5. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\KNOWLEDGE\skills\vibe-trading-exit-logic.md`
6. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\KNOWLEDGE\skills\vibe-trading-entry-regime-filters.md`
7. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\KNOWLEDGE\skills\vibe-trading-options-bot.md`
8. `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\rules\signal_promotion_rules.md`

The worktree is intentionally dirty and contains Kenny/Codex work. Preserve existing changes. Do not reset, revert, clean, or replace files wholesale.

## Bot And System File Map

### Core Execution Bots

- Flip Bot: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\flip_bot.py`
- IWM/options bot: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\iwm_options_bot.py`
- Shared execution guard: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\execution_guard.py`
- Portfolio/manual risk kill switch: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\risk_kill_switch.py`
- Portfolio monitor: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\portfolio_monitor.py`
- Shadow consensus adapter: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\shadow_consensus.py`
- P&L tracker: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\pnl_tracker.py`
- Trading dashboard helpers: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\trading_dashboard.py`

### Flip Bot Learning And Selection

- Trusted shadow lifecycle evaluator: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\flip_shadow_pnl_evaluator.py`
- Rolling learning report: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\flip_bot_learning_report.py`
- Shadow candidate report: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\flip_shadow_candidates_report.py`
- Daily Edge orchestrator: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\daily_edge_orchestrator.py`
- Missed-runner review: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\missed_banger_review.py`
- Closed-trade postmortem: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\closed_trade_postmortem.py`
- Loop closure: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\loop_closure_report.py`

### Market Context And Selection Inputs

- Candlestick context: `scripts\candlestick_context_scanner.py`
- Higher-timeframe map: `scripts\higher_timeframe_market_map.py`
- Catalyst calendar: `scripts\market_catalyst_calendar.py`
- Market force: `scripts\market_force_score.py`
- Breadth: `scripts\market_breadth_uptrend_scanner.py`
- Distribution pressure: `scripts\distribution_day_scanner.py`
- Opening range: `scripts\opening_range_breadth_scanner.py`
- Options liquidity: `scripts\options_liquidity_feasibility.py`
- Adaptive options playbook: `scripts\adaptive_options_shadow_playbook.py`
- Shadow consensus: `scripts\shadow_consensus_gate.py`
- Kronos adapter: `scripts\kronos_market_forecaster.py`
- Market data layer: `scripts\market_data.py`

All paths above are under:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

### Control Plane And Reports

- Dashboard generator: `scripts\generate_dashboard.py`
- Signal health: `scripts\signal_stack_health_report.py`
- Signal leaderboard: `scripts\signal_stack_leaderboard.py`
- Signal grades: `scripts\signal_stack_grades.py`
- Execution audit: `scripts\execution_gate_audit.py`
- Bot status: `scripts\bot_status_snapshot.py`
- Daily EOD: `scripts\daily_eod_summary.py`
- Nightly task queue: `scripts\nightly_research_loop.py`
- Schedule alignment: `scripts\market_schedule_alignment.py`
- Signal registry: `research\signal_registry.json`

### Tests To Extend

- `agent\tests\test_flip_bot_safety.py`
- `agent\tests\test_iwm_options_confidence_gate.py`
- `agent\tests\test_shadow_consensus_exit_advice.py`
- `agent\tests\test_shadow_consensus_gate.py`
- `agent\tests\test_flip_shadow_pnl_evaluator.py`
- `agent\tests\test_flip_bot_learning_report.py`
- `agent\tests\test_daily_edge_orchestrator.py`
- `agent\tests\test_bot_status_snapshot.py`
- `agent\tests\test_signal_stack_health_report.py`
- `agent\tests\test_signal_stack_leaderboard.py`
- `agent\tests\test_signal_stack_grades.py`
- `agent\tests\test_generate_dashboard.py`
- `agent\tests\test_execution_gate_audit.py`

## Runtime State And Logs

Do not place secrets in reports or handoffs.

- Environment/credentials: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\.env`
- Flip trades: `C:\Users\kenne\.vibe-trading\flip-trades.json`
- Options trades: `C:\Users\kenne\.vibe-trading\options-trades.json`
- Portfolio kill switch: `C:\Users\kenne\.vibe-trading\PORTFOLIO_KILL_SWITCH.json`
- Manual reset file: `C:\Users\kenne\.vibe-trading\MANUAL_RESET_REQUIRED.json`
- Flip log: `C:\Users\kenne\.vibe-trading\logs\flip-bot.log`
- Options log: `C:\Users\kenne\.vibe-trading\logs\options-bot.log`
- Reports: `C:\Users\kenne\.vibe-trading\reports`
- Dashboard: `C:\Users\kenne\.vibe-trading\dashboard.html`

Never delete, mock, or silently rewrite kill-switch/manual-reset files.

## Current Verified State

### Operational Checks

- Signal health: `OK=44 STALE=0 MISSING=0 ERROR=0`
- Schedule alignment: `42/42`, zero issues
- Execution audit: `passed=True signals=87 issues=0 warnings=1`
- Known audit warning: read-only Alpaca account/position access in `portfolio_concentration_monitor.py`
- Broad affected test suite: `97 passed`
- Final focused suite: `47 passed`
- Python compile check: passed

### Flip Bot Evidence After Risk Hardening

Use 2026-06-29 as the post-hardening evidence boundary. The earlier 69-contract loss used obsolete sizing and is shown separately as a legacy risk failure.

- Symbol: SPY
- Closed trades: 10
- Winners: 8
- Losers: 2
- Win rate: 80%
- Net paper P&L: `+$2,538`
- Gross profit: `$2,923`
- Gross loss: `$385`
- Profit factor: `7.59`
- Average P&L: `$253.80`
- Capture samples: 5
- Average capture efficiency: `0.678`
- Average giveback: `18.92 percentage points`
- Poor-capture trades: 2
- Armed winners closed negative: 0

Current execution focus is SPY. No non-SPY challenger is promotion-eligible.

### Shadow Evidence Reset

The old Flip shadow log was not trustworthy for symbol promotion:

- 754 legacy rows are now excluded.
- Problems included repeated setup snapshots, incomplete lifecycle tracking, stale-session data, and test contamination.
- Trusted schema-v2 completed challenger lifecycles currently equal 0.
- Preserve legacy rows for audit, but do not use them for readiness, ranking, or optimization.

### Current P0 Blocker

`STATUS.md` is `action_required` because Alpaca option positions do not reconcile with durable options-trade state.

- Broker option positions: 6
- Active tracked group: 1
- Expected active legs: 4
- Missing expected leg: `IWM260807P00277000`
- Untracked broker legs:
  - `IWM260807C00317500`
  - `IWM260807C00320000`
  - `IWM260807P00279000`
- The three untracked legs also appear in a trade already marked closed.

Keep new options entries blocked. Do not auto-close positions or rewrite trade state from inference alone. Reconcile broker orders, fills, positions, and intended multi-leg groups read-only first. Any broker close or durable-state repair requires Kenny's explicit approval.

## Important Fixes Already Implemented

Do not accidentally remove or weaken these:

1. Options state requires two separate flat broker observations before groups are marked closed.
2. Missing or untracked option legs veto new options entries.
3. Bot Status, Daily EOD, and Nightly Queue propagate position-integrity failures.
4. Kronos is scheduled but remains shadow-only and currently model-unavailable.
5. Flip execution defaults to SPY through `FLIP_EXECUTION_SYMBOLS`.
6. Non-SPY symbols remain shadow-only until formal promotion.
7. Bull confidence is no longer padded from 8.0 to 8.5.
8. Bull entries require all SPY/QQQ/IWM leaders at genuine guard-grade confidence.
9. Bear entries require SPY plus at least one confirming leader.
10. Same-day same-direction re-entry requires materially stronger fresh evidence.
11. ATM option estimates prefer live Alpaca midpoint over stale last trade.
12. Intraday bars reject previous-session data.
13. Shadow candidates use schema-v2 entry/mark/exit lifecycles.
14. Once Flip profit protection arms, excessive giveback exits even if current P&L slipped slightly negative.
15. Live execution remains disabled by default.

## Fable 5 Upgrade Program

Work one bounded phase at a time. Findings should lead each phase. Implement and verify the highest-risk issue before expanding scope.

### Phase 0 - Position And Order Integrity

This is the active P0.

- Reconstruct the IWM broker truth from positions, nested multi-leg orders, fills, and durable state.
- Identify the exact event that marked the old group closed while legs remained open.
- Design a deterministic reconciliation state machine:
  - tracked
  - partially filled
  - open
  - exit pending
  - closing
  - partially closed
  - flat pending confirmation
  - closed
  - manual review
- Make state writes atomic and lock-safe.
- Ensure transient empty broker responses cannot advance durable state.
- Detect duplicate ownership of an OCC leg across active groups.
- Detect closed-state legs still open at the broker.
- Produce a read-only reconciliation plan. Do not place repair orders.

### Phase 1 - Flip Bot Trade Quality

- Keep SPY as the execution benchmark unless promotion rules are satisfied.
- Audit entry timing by minute, setup age, distance from VWAP, ORB state, and breadth alignment.
- Detect late/chasing entries and direction changes before submission.
- Require complete current-session data and live option quotes.
- Measure spread, quote age, expected slippage, and fill quality before and after entry.
- Evaluate call/put strike and expiry selection; compare ATM versus controlled debit spreads.
- Improve rejection explanations so every skipped SPY setup has one primary reason.
- Do not lower confidence thresholds to create more trades.

### Phase 2 - Exit Excellence

- Measure MFE, MAE, exit return, giveback, capture efficiency, time-to-peak, and post-exit continuation.
- Compare target, ratchet, time exit, direction-flip exit, and liquidity exit using walk-forward data.
- Test profit-lock models without changing production thresholds until evidence is sufficient.
- Model five-minute monitoring gaps and option-price jumps.
- Ensure an armed winner cannot silently fall through every exit condition.
- Add close-order idempotency and explicit pending/filled/rejected lifecycle tracking.
- Evaluate partial exits in shadow only before any execution change.
- Never claim a perfect exit; optimize expected capture and downside control.

### Phase 3 - Instrument Selection

- Treat SPY as the benchmark, not an assumption.
- Build trustworthy challenger scorecards for QQQ, IWM, AAPL, NVDA, META, and TSLA.
- Rank only complete schema-v2 lifecycles.
- Use conservative metrics:
  - completed trading days
  - completed setup count
  - win/loss rate under modeled exits
  - median and average modeled return
  - capture efficiency
  - downside tail
  - spread and quote quality
  - slippage sensitivity
  - regime-specific performance
- Use walk-forward data only; never rank from same-day future information.
- Require `rules\signal_promotion_rules.md`, 30 trading days, 10 completed actionable lifecycles, independent review, and Kenny approval before execution promotion.

### Phase 4 - Shadow Logger Conversion

Every shadow logger must have a decision-use contract. Classify each as:

- safety veto
- regime context
- candidate generator
- entry confirmation
- exit warning
- learning-only
- retire/disable

For every logger, require:

- unique actionable event definition
- source timestamp and session date
- no duplicate event inflation
- entry and exit lifecycle where applicable
- forward outcome label
- sample count based on events, not rows
- counterfactual skip outcome
- promotion blockers
- explicit non-goals

Retire or archive loggers that cannot demonstrate a useful decision or learning role. Fewer trustworthy signals are better than dozens of decorative reports.

### Phase 5 - Options Bot Strategy Quality

- Audit iron-condor and put-spread selection by regime, IV rank source, DTE, delta, width, credit/risk, earnings, catalyst, liquidity, and portfolio overlap.
- Replace weak HV-proxy assumptions with clearly labeled confidence reductions; do not present proxy IV rank as equivalent to true IV rank.
- Model stop overshoot, multi-leg slippage, and partial close risk.
- Prefer broker-supported grouped close behavior where safely available and tested.
- Block new entries whenever position integrity is unknown.
- Add deterministic recovery tests for partial fills, partial closes, shared legs, rejected closes, and API timeouts.

### Phase 6 - Data And Time Correctness

- Add exchange-calendar awareness for holidays and half days.
- Normalize all timestamps with explicit timezone and source timestamp.
- Reject stale intraday, option, catalyst, and regime inputs.
- Record provider, fallback provider, quote age, and adjustment mode.
- Test Alpaca/yfinance fallback disagreement.
- Make data failures fail closed for execution while still producing useful diagnostics.

### Phase 7 - Backtesting And Validation

- Build event-driven replay for actual entry and exit rules.
- Include realistic option bid/ask, commissions/fees if applicable, slippage, quote cadence, and no-fill cases.
- Use chronological train/validation/test splits and walk-forward evaluation.
- Require strategy-leak audit before accepting results.
- Report expectancy, profit factor, drawdown, loss tails, exposure time, trade count, and parameter sensitivity.
- Avoid optimizing on the ten known SPY trades.
- Compare against simple baselines and no-trade behavior.

### Phase 8 - Operations And Observability

- Ensure every scheduled task has heartbeat, last success, duration, output date, and error reason.
- Detect overlapping runs and add safe single-instance behavior.
- Add stale-report lineage to the dashboard.
- Alert once per incident with recovery notification; avoid alert floods.
- Keep Daily Edge focused on decisions, not report volume.
- Make STATUS.md and the dashboard agree on the highest-priority blocker.

### Phase 9 - Code Quality And Security

- Add atomic JSON/JSONL writes where durable state matters.
- Add file locking or single-writer discipline.
- Remove mutable default arguments.
- Improve type safety around broker payloads and report schemas.
- Redact credentials and broker identifiers from errors/reports.
- Keep order-capable code isolated from read-only analytics.
- Preserve ASCII unless editing an existing Unicode section deliberately.

## Hard Safety Rules

- Never enable live trading.
- Never set `LIVE_EXECUTION_ENABLED` or `FLIP_LIVE_EXECUTION_ENABLED` true.
- Never raise `MAX_CONTRACTS` above 5.
- Never raise per-trade risk above 2%.
- Never delete or mock kill-switch/manual-reset files.
- Never loosen the execution guard to increase trade count.
- Never wire social, X, prediction-market, copy-trader, PMXT, or screenshot context directly to orders.
- Never promote a scanner without the formal promotion rules.
- Never auto-close the currently mismatched IWM legs from inference.
- Never rewrite Kenny/Codex changes wholesale.
- Never use hindsight metrics as same-day selection inputs.
- All new reports must default to `execution_enabled: false` and `can_submit_orders: false` where applicable.

## Required Verification

Use system Python unless a dependency specifically requires another runner.

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

python -m pytest agent\tests\test_flip_bot_safety.py agent\tests\test_flip_shadow_pnl_evaluator.py agent\tests\test_flip_bot_learning_report.py agent\tests\test_daily_edge_orchestrator.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_signal_stack_grades.py agent\tests\test_generate_dashboard.py agent\tests\test_execution_gate_audit.py agent\tests\test_shadow_consensus_gate.py agent\tests\test_shadow_consensus_exit_advice.py agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_bot_status_snapshot.py agent\tests\test_signal_stack_health_report.py agent\tests\test_daily_eod_summary.py agent\tests\test_nightly_research_loop.py agent\tests\test_market_schedule_alignment.py -q -p no:cacheprovider

python -m compileall -q strategies scripts
python scripts\execution_gate_audit.py --print
python scripts\signal_stack_health_report.py
python scripts\market_schedule_alignment.py --print
python scripts\flip_shadow_pnl_evaluator.py --print
python scripts\flip_bot_learning_report.py --print
python scripts\daily_edge_orchestrator.py --print
python scripts\generate_dashboard.py
```

Expected minimum:

- affected tests pass
- compile passes
- execution audit has zero issues
- no live flag changes
- no kill-switch changes
- reports remain read-only
- dashboard regenerates
- any changed execution behavior has a focused regression test

## Definition Of Elite Status

Do not label the system elite merely because tests pass or the dashboard is green.

Elite status requires all of the following:

1. Broker truth and durable state reconcile deterministically.
2. No strategy can enter on stale or ambiguous data.
3. Position sizing and portfolio limits are enforced centrally.
4. Entries have forward-tested positive expectancy after realistic costs.
5. Exits demonstrate acceptable capture and controlled downside out of sample.
6. Instrument selection uses only prior evidence and current observable data.
7. Shadow experiments have complete lifecycles and honest counterfactual outcomes.
8. Every trade, skip, rejection, and exit is attributable to one primary decision reason.
9. Scheduled operations recover cleanly and surface failure immediately.
10. No component can self-promote, bypass risk, or silently submit orders.

## Required Claude Deliverable

At the end of each phase, leave:

- findings ordered by severity
- exact files changed
- tests and commands run
- before/after behavior
- current runtime/report state
- remaining risks and evidence gaps
- next single highest-value task
- a new dated handoff in `CODEx_CLAUDE_COLLAB`

Start with Phase 0. Do not bury the active broker/state mismatch under strategy research. Once Phase 0 has a verified read-only reconciliation and a safe repair plan, continue to the highest-value Flip Bot and learning upgrades that can be completed without loosening risk.
