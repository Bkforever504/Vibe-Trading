# Claude Handoff: Options Research Validity and Next Competitive Jump

Date: 2026-07-13 CT

## Objective

Continue improving the autonomous options stack without weakening live/paper execution controls, changing risk thresholds, or treating social/public-chain activity as proven edge. The current upgrade makes research failures count, captures forward Flip features, adds option-surface context, and blocks cheap-option lottery candidates in shadow ranking only.

## Repository and Runtime

- Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
- Runtime state: `C:\Users\kenne\.vibe-trading`
- Reports: `C:\Users\kenne\.vibe-trading\reports`
- Flip state: `C:\Users\kenne\.vibe-trading\flip-trades.json`
- This worktree is heavily dirty. Preserve user/Codex/Claude changes and do not revert unrelated files.

## Implemented in This Phase

### 1. Option Surface and Unsigned Flow Context

- `scripts/options_surface_intelligence.py`
- `scripts/run_options_surface_intelligence.ps1`
- `agent/tests/test_options_surface_intelligence.py`

Computes ATM IV, put/call wings, skew, term slope, implied move, spreads, OI/volume ratios, unsigned unusual volume/OI, and retail-lottery risk. Public volume is explicitly unsigned and `institutional_flow_available=false`. It cannot place orders.

Live 2026-07-13 snapshot: 8/8 chains parsed. RIVN was flagged for retail-lottery risk; SPY, NVDA, NFLX, QQQ, HOOD, IWM, and AAPL were not. This affected shadow ranking only.

### 2. Daily Universe Surface Integration

- `scripts/daily_options_universe_ranker.py`
- `agent/tests/test_daily_options_universe_ranker.py`

Surface usability adds research context. A non-SPY cheap-option lottery flag blocks that symbol from shadow challenger ranking. SPY remains the execution benchmark and no execution-symbol set changed.

### 3. Immutable Edge Trial Ledger

- `scripts/edge_trial_ledger.py`
- `scripts/run_edge_trial_ledger_report.ps1`
- `strategies/backtest.py`
- `agent/tests/test_edge_trial_ledger.py`

Every new backtest variant can be appended with a deterministic ID, hypothesis, data window, stage, cost model, parameters, metrics, source, and code version. Duplicate records are rejected. All trials count in the family denominator. Reports include Bonferroni and Benjamini-Hochberg results.

Promotion review requires OOS/forward stage, Bonferroni pass, at least 30 OOS trades, positive expectancy, PF above 1, and drawdown coverage. The ledger cannot promote or execute. Current ledger count is correctly zero; do not fabricate historical trials.

### 4. Forward Flip Feature Telemetry and Ablation

- `strategies/flip_bot.py`: `_entry_feature_snapshot()` is stored under `entry_quality.feature_snapshot`
- `scripts/flip_feature_ablation_report.py`
- `scripts/run_flip_feature_ablation_report.ps1`
- `agent/tests/test_flip_feature_ablation_report.py`
- `agent/tests/test_flip_entry_quality.py`

Schema v1 captures strategy/right, VWAP and EMA relationships, EMA slope, session color, extension/pullback state, breadth, ORB, TTM state/release/momentum, shadow consensus, spread, and quote age. This is telemetry only.

Ablation compares normalized returns for present/absent feature groups. It requires 30 known trades, 10 per group, positive lift, and Bonferroni significance before `review_eligible=true`. It makes no causal claim and cannot change behavior. Current state: 11 closed Flip trades, 0 schema-v1 closed trades, 0 review-eligible features. Legacy fields are not imputed.

### 5. Governance and Automation

- `scripts/elite_bot_readiness_scorecard.py`: added Research validity category and new sources
- `scripts/market_schedule_alignment.py`
- `scripts/signal_stack_health_report.py`
- `scripts/register_elite_bot_scorecard_tasks.ps1`
- `research/signal_registry.json`

Registered Windows tasks:

- `\VibeTrade\OptionsSurfaceIntelligence` at 19:05 CT
- `\VibeTrade\DailyOptionsUniverseRanker` at 19:12 CT
- `\VibeTrade\FlipExitQualityReport` at 19:17 CT
- `\VibeTrade\FlipFeatureAblationReport` at 19:18 CT
- `\VibeTrade\EdgeTrialLedgerReport` at 19:53 CT
- `\VibeTrade\EliteBotReadinessScorecard` at 20:03 CT

## Verified Host State

- Focused and broad tests: 187 passed, 1 external deprecation warning
- Compile: clean
- Execution-gate audit: passed, 0 issues
- Schedule alignment: passed, 53/53
- Signal health: 52 OK, 0 stale, 0 missing, 0 error
- Readiness score: 7.1/10, evidence building
- Verified 10 categories: Operational integrity, Risk controls, Autonomous safety
- Entry quality: 7; Universe: 5; Exit quality: 4; Learning: 8; Research validity: 6; Proven profitability: 4
- Universe: 59 ranked, 4 shadow challengers, 0 promotion-review candidates
- No order, live flag, risk threshold, stop, target, sizing, or kill-switch behavior changed in this phase

## Exact Recheck

```powershell
Set-Location C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

python -m pytest agent/tests/test_flip_bot_safety.py agent/tests/test_flip_decision_log.py agent/tests/test_flip_bot_learning_report.py agent/tests/test_flip_exit_quality_report.py agent/tests/test_flip_shadow_pnl_evaluator.py agent/tests/test_flip_entry_quality.py agent/tests/test_flip_feature_ablation_report.py agent/tests/test_daily_options_universe_ranker.py agent/tests/test_options_surface_intelligence.py agent/tests/test_edge_trial_ledger.py agent/tests/test_options_position_reconciler.py agent/tests/test_options_state_integrity.py agent/tests/test_options_reporting.py agent/tests/test_execution_gate_audit.py agent/tests/test_strategy_safety_layers.py agent/tests/test_iwm_options_confidence_gate.py agent/tests/test_signal_stack_health_report.py agent/tests/test_market_schedule_alignment.py agent/tests/test_elite_bot_readiness_scorecard.py agent/tests/test_loop_readiness_audit.py agent/tests/test_loop_closure_report.py agent/tests/test_self_improving_strategy_verifier.py agent/tests/test_signal_stack_grades.py agent/tests/test_nightly_alpha_factory.py agent/tests/test_weekly_hot_instrument_report.py agent/tests/test_options_liquidity_feasibility.py test_execution_guard.py test_flip_bot_execution_guard.py test_flip_bot_script_execution.py test_iwm_options_execution_guard.py -q

python scripts\execution_gate_audit.py
python scripts\market_schedule_alignment.py --print
python scripts\signal_stack_health_report.py
python scripts\elite_bot_readiness_scorecard.py --print
```

## Next Competitive Jump

Do these in order. Evidence before behavior.

1. Add a vendor-neutral point-in-time option quote interface that records NBBO, quote timestamp, underlying price, IV, delta/gamma/theta/vega, OI, volume, and trade condition at signal, fill, each monitor sample, and exit. Existing yfinance surface data is research context, not execution-grade history.
2. Add an optional licensed/classified OPRA adapter for buyer/seller initiation and opening/closing inference. Keep public snapshots labeled unsigned. Missing classified data must fail to `unknown`, never “smart money.”
3. Build an option lifecycle dataset keyed by trade/order/contract ID. Finish exit capture telemetry and report path completeness, stale quotes, spread cost, Greek decay, MFE/MAE, capture efficiency, and reason-specific exits.
4. Preregister regime-specific hypotheses in the immutable ledger before running sweeps. Use purged walk-forward/OOS windows, realistic spread/slippage/fees, family-wide trial counts, and stability checks across volatility, trend, event, and time-of-day regimes.
5. After at least 30 schema-v1 closed Flip trades, use ablation only to nominate small, reversible shadow experiments. Require separate forward replication and explicit Kenny approval before any entry/exit change.

## Hard Stops

- Do not change `EXECUTION_SYMBOLS`, live/paper flags, risk limits, stop/target logic, sizing, reconciliation, kill switches, or broker paths without explicit user approval.
- Do not auto-promote a feature, symbol, or strategy.
- Do not backfill or fabricate historical trials or feature telemetry.
- Do not label unsigned public option volume as institutional buying/selling.
- Do not optimize on the same sample used to score or approve a proposal.
- Stop and report if point-in-time quote provenance or timestamps cannot be proven.
