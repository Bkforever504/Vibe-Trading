# Claude Handoff: Elite Scorecard, Daily Universe Ranking, and Automated Exit Learning

Date: 2026-07-13 CT
Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Runtime: `C:\Users\kenne\.vibe-trading`

## Objective

Move every bot process toward a defensible 10/10 without inflating scores from tiny samples or weakening safety. Engineering controls may earn 10 through deterministic verification. Entry, exit, universe, learning, and profitability remain capped until forward evidence earns higher scores.

## Current Verified Scorecard

Runtime report:

`C:\Users\kenne\.vibe-trading\reports\elite-bot-readiness-scorecard.json`

Overall: **7.2/10**, status `evidence_building`.

| Category | Score | Evidence cap | State |
|---|---:|---:|---|
| Operational integrity | 10 | 10 | verified |
| Risk controls | 10 | 10 | verified |
| Entry quality | 7 | 7 | 10 post-hardening trades; sample cap active |
| Daily universe selection | 5 | 5 | no challenger has passed promotion evidence |
| Exit quality | 4 | 4 | zero complete forward paths yet; legacy data is not estimated |
| Learning loop | 8 | 8 | process is wired; outcome evidence remains immature |
| Proven profitability | 4 | 4 | 10 post-hardening trades; no durable drawdown series |
| Autonomous safety | 10 | 10 | verified |

The scoring rule is the lower of process score and evidence cap. Do not remove or relax these caps to make the dashboard look better.

## New Implementation

### Daily options universe ranker

Files:

- `scripts/daily_options_universe_ranker.py`
- `scripts/run_daily_options_universe_ranker.ps1`
- `agent/tests/test_daily_options_universe_ranker.py`

Runtime report:

`C:\Users\kenne\.vibe-trading\reports\daily-options-universe-ranker.json`

Behavior:

- Combines weekly hot-instrument context, direct option-chain feasibility, deep-liquid scores, shadow outcomes, and catalyst context.
- Option-chain liquidity is a hard blocker. Social attention cannot override it.
- Tiny samples are capped at 49/100 and cannot appear promotion-ready.
- SPY remains the execution benchmark.
- Every non-SPY name remains shadow-only; `non_spy_execution_allowed=false`.
- No broker client and no order path exist in this script.

Current result:

- Execution benchmark: SPY, direct liquidity gate passing.
- Promotion review: 0.
- Shadow challengers: RIVN, NFLX, HOOD, NVDA, QQQ.
- Blocked: 53 symbols, including names without a direct chain check or with a failed chain gate.
- Challenger samples are only 1-4 completed lifecycles over 1-2 trading days. Do not promote.

### Evidence-capped elite scorecard

Files:

- `scripts/elite_bot_readiness_scorecard.py`
- `scripts/run_elite_bot_readiness_scorecard.ps1`
- `agent/tests/test_elite_bot_readiness_scorecard.py`

Hard gates include:

- Entry quality: 100 post-hardening trades and 60 days before a 10 is possible.
- Universe: a challenger must mature through OOS promotion evidence; 50 completed lifecycles and 60 days are required for a 10.
- Exit quality: 50 complete forward paths, average capture at least 0.60, and average giveback at most 25%.
- Profitability: 200 post-hardening trades, 120 days, positive expectancy/profit factor, and a durable maximum-drawdown series. Profitability is currently hard-capped below 10 because drawdown is not yet recorded in this report.

### Automated exit-quality logging

Files:

- `scripts/flip_exit_quality_report.py`
- `scripts/run_flip_exit_quality_report.ps1`
- Log: `data/flip_exit_quality_log.jsonl`

The report remains read-only and marks missing legacy telemetry `insufficient_data`; it does not estimate or backfill paths.

### Scheduling and health

Files:

- `scripts/register_elite_bot_scorecard_tasks.ps1`
- `scripts/market_schedule_alignment.py`
- `scripts/signal_stack_health_report.py`

Registered and Ready:

- `\VibeTrade\DailyOptionsUniverseRanker` at 19:12 CT.
- `\VibeTrade\FlipExitQualityReport` at 19:17 CT.
- `\VibeTrade\EliteBotReadinessScorecard` at 20:03 CT.
- `\VibeTrade\FlipBotLearningReport` at 19:15 CT was documented previously but missing on-host; it is now registered and Ready.

Current scheduler verification: 50/50 aligned, zero issues, two known extra-start-time warnings.

Current signal health: 49 OK, zero stale, zero missing, zero error.

## Position Integrity

Read-only live broker reconciliation at `2026-07-14T02:03:16Z`:

- Signed expected book equals signed broker book.
- Zero unexplained residual.
- Entries remain `False` because status is `review_required`.
- Two open IWM condors share `IWM260807P00277000` on opposite sides, so that contract nets to zero at the broker.
- Both groups remain `manual_review`; no broker repair order is required.
- Do not weaken the reconciliation or netted-leg quote-mark protections.

## Current Flip Evidence

Post-hardening window from 2026-06-29:

- Closed trades: 10.
- Net P&L: +$2,538 paper.
- Win rate: 80%.
- Profit factor: 7.59.
- Expectancy: +$253.80 per trade.
- Capture telemetry sample: 5.
- Complete new exit-quality paths: 0 because existing closed trades predate the full forward schema.

These are encouraging but not enough to promise daily profit or call the bot elite. Do not use the win rate alone; preserve expectancy, payoff, capture, and loss controls.

## Safety Rules That Must Not Change

- Do not change `STOP_MULT=0.70`.
- Do not increase `MAX_CONTRACTS=5`.
- Do not increase the 2% risk budget.
- Do not loosen daily loss guards, kill switches, execution gates, quote-age gates, or reconciliation.
- Do not enable a non-SPY execution symbol from the universe report.
- Do not auto-promote any social, shadow, Kronos, or external-strategy signal.
- Do not submit, modify, or cancel broker orders while working this queue.

## Next Bounded Queue

1. Add a read-only post-hardening equity-curve and maximum-drawdown report using durable realized P&L. Deduplicate by durable trade/order identity and test legacy exclusions. Do not turn it into an execution gate yet.
2. Let the new entry/exit telemetry collect forward paths. Do not change exit behavior before at least 10 complete paths; prefer 30 for comparison and 50 for scorecard maturity.
3. Review daily universe rankings after 10 completed samples per challenger and again after 30 trading days. Negative OOS expectancy remains a blocker regardless of social popularity.
4. At 30 and 50 post-hardening Flip trades, run a frozen-policy review of expectancy, profit factor, capture, giveback, MAE, drawdown, and regime slices. Evidence before behavior.
5. Keep tomorrow's catalyst layer fresh. The current calendar marks 2026-07-14 CPI as high impact; dynamic geopolitical risk must be refreshed intraday rather than copied from this handoff.

## Verification Run

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

python -m pytest agent\tests\test_flip_bot_safety.py agent\tests\test_flip_entry_quality.py agent\tests\test_flip_bear_trend.py agent\tests\test_flip_shadow_pnl_evaluator.py agent\tests\test_flip_bot_learning_report.py agent\tests\test_daily_edge_orchestrator.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_signal_stack_grades.py agent\tests\test_generate_dashboard.py agent\tests\test_execution_gate_audit.py agent\tests\test_shadow_consensus_gate.py agent\tests\test_shadow_consensus_exit_advice.py agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_options_state_integrity.py agent\tests\test_options_position_reconciler.py agent\tests\test_bot_status_snapshot.py agent\tests\test_signal_stack_health_report.py agent\tests\test_daily_eod_summary.py agent\tests\test_nightly_research_loop.py agent\tests\test_market_schedule_alignment.py agent\tests\test_flip_decision_log.py agent\tests\test_flip_exit_quality_report.py agent\tests\test_options_reporting.py agent\tests\test_closed_trade_postmortem.py agent\tests\test_loop_closure_report.py agent\tests\test_daily_options_universe_ranker.py agent\tests\test_elite_bot_readiness_scorecard.py -q -p no:cacheprovider

python -m pytest test_bull_trend_spread.py test_execution_guard.py test_flip_bot_execution_guard.py test_flip_bot_script_execution.py test_iwm_options_execution_guard.py -q -p no:cacheprovider

python scripts\execution_gate_audit.py --print --fail-on-issues
python scripts\options_position_reconciler.py --print
python scripts\market_schedule_alignment.py --print
python scripts\signal_stack_health_report.py
python scripts\daily_options_universe_ranker.py --print
python scripts\flip_exit_quality_report.py --print
python scripts\elite_bot_readiness_scorecard.py --print
```

Verified in this session:

- 165 targeted bot tests passed.
- 21 root execution tests passed.
- 13 focused new/integration tests passed (included in the 165 where overlapping).
- Compile clean.
- Execution audit: 87 signals, zero issues, one read-only broker-client warning.
- Schedule: 50/50 aligned, zero issues.
- Health: 49 OK, zero stale/missing/error.
- No orders submitted and no risk/live thresholds changed.

## Dirty Worktree Warning

The repository was already heavily dirty with many user/Claude/Codex changes and runtime logs. Preserve all unrelated work. Do not reset, clean, checkout, or rewrite files outside the bounded task.
