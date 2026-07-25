# Claude Code Handoff: Flip, Options, and Topstep Bot Upgrade

Date: 2026-07-24 CT

Repository:

```text
C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
```

Runtime state:

```text
C:\Users\kenne\.vibe-trading
```

This handoff supersedes the bot-upgrade scope in
`CLAUDE_CODE_HANDOFF_EDGE_DISCOVERY_ROBINHOOD_2026-07-24.md`. That broader
document remains useful for research ideas, but the current assignment is
specifically the three trading systems below.

## Ultimate Goal

Build three honest, increasingly capable paper systems that can eventually
earn promotion through reproducible forward evidence:

1. **Flip Bot:** selective directional long calls/puts with executable entries,
   disciplined exits, and complete path attribution.
2. **Options Bot:** defined-risk premium selling with realistic multi-leg
   fills, Greeks/IV attribution, and portfolio-level risk controls.
3. **Topstep Bot:** a separate MES prop-firm system that proves an intraday
   edge while respecting Topstep-style drawdown and consistency constraints.

The economic goal is consistent positive expectancy with minimal drawdown,
not a promised daily income. A $1,000 account cannot safely or consistently
produce $100-$200 every day. The credible capital path is to validate the
Alpaca bots in paper and validate one-contract MES for eventual funded-capital
use. No bot is live-ready today.

## Non-Negotiable Boundaries

- Do not enable live trading.
- Do not enable the disabled MES scheduled task.
- Do not purchase Topstep, Databento, OPRA, or any other data/service.
- Do not change risk, sizing, stops, targets, contract caps, kill switches,
  execution symbols, or broker endpoints.
- Do not run Flip or Options entry scripts while testing. Use mocks, fixtures,
  read-only reports, and explicit dry-run paths.
- Do not promote a challenger automatically.
- The learning system may observe, diagnose, rank, and nominate. It may not
  mutate production behavior.
- Preserve the dirty worktree. Do not revert, clean, or rewrite unrelated
  user/Codex/Claude files.
- Work on one active task at a time, as required by `STATUS.md`.

## Critical Architecture Correction

The learning ledger currently contains taxonomy contamination. Examples
include:

- bearish long puts evaluated using bullish-direction rules;
- bullish long calls evaluated using bearish-direction rules;
- long debit options evaluated using credit-spread rules;
- missing or `unknown` entry pattern, expected move, and trend alignment.

Do not tune signals from contaminated labels. Repair attribution first.

Create a canonical, versioned lifecycle schema with a required `bot_family`:

```text
flip_directional_debit
options_defined_risk_credit
topstep_mes_futures
```

Each family must have its own:

- trade identity and parent order identity;
- signal, decision, order, fill, monitor, and exit events;
- return and risk formula;
- direction semantics;
- mistake taxonomy;
- feature schema version;
- data-provider and timestamp provenance;
- execution-cost model;
- eligibility and promotion gates.

Shared portfolio observations may reference several families, but a lesson
from one family must never become a production rule for another without a new
preregistered cross-family experiment.

## Current System State

### Flip Bot

Primary files:

```text
strategies\flip_bot.py
strategies\flip_scanner.py
strategies\flip_contract_ranker.py
strategies\flip_day_type_router.py
strategies\flip_live_readiness.py
strategies\flip_retest_quality.py
strategies\flip_shadow_setup_challengers.py
scripts\flip_bot_learning_report.py
scripts\flip_exit_quality_report.py
scripts\flip_feature_ablation_report.py
scripts\flip_path_telemetry_completeness.py
scripts\flip_execution_challenger_report.py
scripts\flip_shadow_pnl_evaluator.py
scripts\flip_equity_curve_report.py
scripts\flip_decision_missed_banger_review.py
```

Runtime:

```text
C:\Users\kenne\.vibe-trading\flip-trades.json
C:\Users\kenne\.vibe-trading\logs\flip-decisions.jsonl
C:\Users\kenne\.vibe-trading\logs\flip-bot.log
```

Observed on 2026-07-24:

- 1,589 decision rows: 1,266 skips, 321 blocks, 2 submitted.
- 13 closed SPY trades: 7 calls and 6 puts.
- The trustworthy rolling report uses 12 trades since 2026-06-29:
  66.7% win rate, $2,332 net paper P&L, PF 4.95, $194.33 expectancy.
- This is heterogeneous paper evidence over only 26 days, not proof of edge.
- Readiness remains roughly 5.6/10: risk controls are strong, but exit-path
  completeness and operational integrity remain weak.
- The paper broker account is active; live execution remains disabled.
- The default affordability report shows that a 2% premium cap cannot buy a
  typical option contract at small account sizes.

Succeeded:

- Paper-by-default execution and hard live gate.
- Quote freshness, spread, slippage, position count, and entry guards.
- Broker-confirmed fills and partial-fill reconciliation.
- Resting DAY take-profit at +75% for eligible single-leg trades.
- Race-safe cancellation before software stop/ratchet/time exits.
- Durable path telemetry and read-only learning/ablation reports.

Do not break:

- `CODEX_HANDOFF_2026-07-17_FLIP_RESTING_TAKE_PROFIT.md`
- entry reconciliation;
- resting-target race protection;
- sell-side protection when the entry kill switch is active.

### Options Bot

Primary files:

```text
strategies\iwm_options_bot.py
strategies\options_state.py
scripts\options_position_reconciler.py
scripts\options_surface_intelligence.py
scripts\options_liquidity_feasibility.py
scripts\option_premium_level_logger.py
scripts\daily_options_universe_ranker.py
scripts\adaptive_options_shadow_playbook.py
scripts\liquid_options_edge_shadow.py
```

Runtime:

```text
C:\Users\kenne\.vibe-trading\options-trades.json
C:\Users\kenne\.vibe-trading\logs\options-decisions.jsonl
C:\Users\kenne\.vibe-trading\logs\options-bot.log
```

Observed on 2026-07-24:

- 61 decision rows: 49 skips and 12 submitted.
- Durable state has 16 records: 13 closed and 3 open.
- Strategies include put spreads, recovered multi-leg positions, and iron
  condors.
- The execution lane is paper-only and defined-risk.
- Existing controls include 2% max account risk, daily loss guard, exposure
  cap, liquidity checks, confidence gate, and per-symbol/per-run limits.
- Public option-volume data is unsigned context, not institutional flow.
- Underlying-only replay cannot establish options profitability.

Succeeded:

- Multi-leg durable state and broker reconciliation.
- Defined-risk structures with confidence and liquidity gates.
- Option-surface research context and universe ranking.
- Immutable edge-trial ledger.
- No naked-option strategy.

Main evidence gap:

- no complete point-in-time NBBO/Greeks/IV lifecycle from signal through exit;
- no robust options-specific realized P&L attribution in the current state
  schema;
- no realistic replay of multi-leg fill probability, spread cost, assignment,
  exercise, and early-close behavior.

### Topstep / MES Bot

Primary files:

```text
strategies\topstep_prop_bot.py
strategies\topstep_replay_backtester.py
strategies\mes_sim_candidate.py
strategies\topstepx_practice_adapter.py
scripts\run_ninjatrader_mes_sim.py
scripts\topstepx_practice_probe.py
rules\prop_firms\topstep_topstepx_api.json
rules\prop_firms\topstep_practice_api.json
```

Key evidence:

```text
research\MES_EXECUTABLE_FRONTIER_2026-07-19.md
research\MES_SIGNED_FLOW_FORWARD_PROTOCOL_2026-07-21.md
research\MES_SIGNED_FLOW_ABSORPTION_RESULTS_2026-07-21.md
research\MES_QUOTE_EXHAUSTION_RESULTS_2026-07-20.md
```

Current verdict:

- No tested MES intraday family is deployable.
- The broad 6,400-configuration study found positive-looking finalists, but
  they failed stress, drawdown, and probability-of-ruin standards.
- ORB, sweeps, FVG, VWAP fade, quote imbalance, and quote exhaustion were
  rejected after costs or robustness checks.
- Signed-flow absorption showed research quality but the frozen conjunction
  produced no candidate windows.
- `VibeTradingNinjaTraderMESSim` is disabled and must remain disabled.

The frozen forward protocol requires:

- 30 new outcome-blind research sessions;
- at most one feasible preregistered challenger;
- then 30 later NinjaTrader Sim101 trades;
- PF at least 1.30;
- positive expectancy under stress;
- max drawdown no worse than $200;
- zero prop-rule violations;
- no trade contributing over 25% of net profit;
- independent adversarial review.

## Assignment: Execute in This Order

### P0: Repair Evidence Attribution

Build a migration-free normalization layer. Do not rewrite historical logs.

1. Add a versioned canonical event adapter that reads existing records and
   emits normalized views with `bot_family`, `strategy_family`,
   `instrument_type`, `position_effect`, `direction`, and `outcome_status`.
2. Add family-specific validation. Invalid cross-family fields must become
   `not_applicable`, not false and not a mistake.
3. Quarantine ambiguous records as `unknown` and report them separately.
4. Add a contamination audit showing the count and examples of mismatched
   labels by bot family.
5. Make all learning reports consume normalized views or explicitly declare
   why they cannot yet do so.

Acceptance:

- bearish Flip puts are correctly profitable when the underlying falls;
- bullish Flip calls are correctly profitable when the underlying rises;
- credit spreads use credit/max-risk and closing-debit semantics;
- MES uses point value, fees, slippage, and prop-rule accounting;
- no production behavior changes.

### P1: Flip Evidence Upgrade

1. Finish path completeness for every post-hardening trade:
   entry NBBO, fill, timestamp, underlying, IV/Greeks when available, each
   monitor sample, MFE, MAE, stop/target state, exit order, and broker fill.
2. Reconcile the stop-policy documentation mismatch. The code currently uses
   a 0.70 stop multiplier while older registry text may describe a 50% stop.
   Report the discrepancy only; do not change the stop.
3. Build an affordability report at $300, $500, $1,000, and current paper
   equity using actual observed eligible-contract premiums and spreads.
4. Split results by call/put, strategy, day type, entry window, catalyst,
   spread bucket, and telemetry schema version.
5. Add a walk-forward challenger report for small, preregistered changes.
   No parameter sweep may reuse the final scoring period.
6. Diagnose skipped/blocked decisions against counterfactual underlying moves
   without claiming option P&L when point-in-time option quotes are absent.

Promotion evidence:

- at least 30 closed, schema-current, broker-reconciled paper trades;
- at least 20 trades in each promoted direction or a one-direction-only
  hypothesis declared in advance;
- positive expectancy and PF above 1.30 after realistic spreads/slippage;
- stable positive expectancy after removing the best trade;
- maximum drawdown compatible with the declared small-account risk budget;
- zero duplicate exits, phantom positions, or reconciliation gaps.

### P2: Options Evidence Upgrade

1. Implement a vendor-neutral, append-only option lifecycle dataset keyed by
   signal, trade, order, and OCC contract IDs.
2. Capture provider, NBBO timestamp, bid, ask, midpoint, underlying, IV,
   delta, gamma, theta, vega, OI, volume, and trade condition at signal,
   submission, fill, monitoring, and exit.
3. Add explicit realized P&L fields for multi-leg positions, including
   opening credit, closing debit, fees, partial fills, and recovered trades.
4. Build a conservative multi-leg executable-fill model. Use adverse-side
   prices and stress wider spreads; never assume all legs fill at midpoint.
5. Add assignment/exercise and ex-dividend risk flags.
6. Report performance separately for put spreads and iron condors by IV
   regime, trend, DTE, delta, liquidity, and exit reason.
7. Keep the IWM lane frozen until enough lifecycle-complete trades exist.

Promotion evidence:

- at least 30 lifecycle-complete closed paper positions for a single frozen
  structure;
- positive net expectancy after fees and stressed spread costs;
- PF above 1.30 and no reliance on the best position;
- assignment/exercise paths tested;
- zero naked risk and zero state/broker divergence.

### P3: Cross-Bot Portfolio Coordinator

Create a read-only exposure report before adding any new strategy logic.

It must identify:

- Flip and premium positions sharing SPY/IWM/QQQ or highly correlated beta;
- net delta, gamma, theta, vega, max loss, and expiry concentration;
- same-direction risk hidden across calls, puts, and credit spreads;
- simultaneous daily-loss consumption;
- stale or unreconciled broker positions.

The first version is report-only. It cannot block, size, close, or submit.

### P4: Topstep Edge Work

Do not retune rejected ORB families. Work only from new, preregistered
hypotheses and untouched future data.

1. Verify the signed-flow dataset and forward protocol without consuming an
   outcome window for tuning.
2. Add a strict session recorder and immutable observation ledger for the 30
   future sessions.
3. Add a Topstep rule simulator covering trailing/daily loss, consistency,
   session close, contract cap, and commissions.
4. Add bootstrap/Monte Carlo sequence risk for one MES contract.
5. Add adversarial tests for look-ahead, contract-roll leakage, timezone/DST,
   same-bar stop/target ambiguity, missing bars, and optimistic fills.
6. If the frozen signed-flow conjunction remains too rare, record that
   falsification. Any simpler replacement is a new family and must be
   preregistered before viewing its outcomes.

Do not spend more Databento credits. Use only the existing local files:

```text
data\databento\mes_v0_bbo1s_rth.parquet
data\databento\mes_v0_trades_2025q4.parquet
data\databento\mes_v0_trades_2025-10-01_2026-01-01.dbn.zst
data\databento\mes_signed_flow_windows_2025q4.parquet
```

### P5: Bounded Self-Learning Loop

The loop should become smarter without becoming self-authorizing.

Pipeline:

```text
observe -> normalize -> attribute -> diagnose -> nominate
-> preregister -> shadow -> forward validate -> adversarial review
-> Kenny approval -> manual production change
```

Required controls:

- immutable experiment ID and hypothesis;
- declared family, features, thresholds, cost model, and evaluation window;
- purged/embargoed train-selection-final split;
- all attempted variants counted in multiplicity control;
- champion remains frozen while challengers run;
- minimum sample and stability gates;
- rollback artifact for any approved change;
- no LLM-generated rule can reach execution without tests and approval.

Add an adversarial reviewer report whose explicit job is to find:

- look-ahead and revision bias;
- survivorship and contract-selection bias;
- incorrect P&L/point-value formulas;
- midpoint or perfect-fill assumptions;
- silent missing-data behavior;
- selection-period reuse;
- top-trade/outlier dependence;
- regime concentration;
- capital/affordability mismatch;
- divergence between state and broker.

## Robinhood Role

Codex remote Robinhood access is working, but it is not a drop-in execution
replacement:

- the agentic cash account is agentic-enabled but has no options permission;
- the options-enabled margin account is not agentic-enabled;
- the repo-local Vibe CLI is not yet configured for Robinhood OAuth.

Use Robinhood only for read-only holdings/order/account comparison if the
available connector supports it. Do not place orders, expose account numbers,
or route either options bot to Robinhood.

## Operational Issue Before Strategy Work

`STATUS.md` currently reports 61 healthy outputs and one stale output, plus one
schedule-alignment issue. Fix only the underlying report/schedule plumbing and
prove it is not the checker observing its own running task. Do not change a
signal merely to make health green.

## Required Deliverables

1. A concise implementation report under `CODEx_CLAUDE_COLLAB`.
2. Canonical lifecycle adapter and contamination audit with tests.
3. Bot-specific learning reports that do not mix taxonomies.
4. Read-only cross-bot exposure report with tests.
5. Topstep forward-protocol integrity tests and rule-simulator improvements.
6. Updated `STATUS.md` only if generated by the normal status process.
7. A final table for each bot:
   evidence count, expectancy, PF, max drawdown, path completeness,
   operational integrity, remaining blockers, and confidence score.

Confidence must be evidence-based. A score of 9-10 requires robust
forward/live-sim evidence and clean operations, not code completeness.

## Verification

At minimum, run focused suites for touched files plus:

```powershell
python -m pytest agent\tests\test_flip_bot_safety.py agent\tests\test_flip_entry_quality.py agent\tests\test_flip_bot_learning_report.py agent\tests\test_flip_exit_quality_report.py agent\tests\test_options_position_reconciler.py agent\tests\test_options_state_integrity.py agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_topstep_prop_bot.py agent\tests\test_topstep_replay_backtester.py agent\tests\test_topstepx_practice_adapter.py agent\tests\test_mes_sim_candidate.py -q

python scripts\execution_gate_audit.py
python scripts\market_schedule_alignment.py --print
python scripts\signal_stack_health_report.py
python scripts\elite_bot_readiness_scorecard.py --print
```

If an existing test path has moved, locate the current equivalent rather than
deleting coverage. Stop and report if tests expose a broker-state risk,
unintended execution path, or corrupted historical record.

## First Action

Start with P0 only: build the normalized read-only lifecycle view and
contamination audit. Return the before/after counts and test results before
touching any other bot logic.
