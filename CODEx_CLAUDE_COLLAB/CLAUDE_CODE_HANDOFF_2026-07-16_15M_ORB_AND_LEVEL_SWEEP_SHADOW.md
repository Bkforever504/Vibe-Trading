# Claude Code Handoff: 15m ORB and Prior-Level Sweep Shadow Challengers

Date: 2026-07-16

## Objective

Turn the useful, mechanically testable ideas in Kenny's latest screenshots into forward option-level evidence without granting social-media claims execution authority or contaminating existing Flip promotion metrics.

## Delivered

- Added `strategies/flip_shadow_setup_challengers.py`.
- Added an independent 15-minute ORB challenger:
  - first 15 completed one-minute bars define the range;
  - a later completed candle must close outside;
  - price must make a bounded retest and hold;
  - later invalidation cancels a not-yet-collected signal;
  - prior-day-high/low alignment is context, not proof;
  - modeled underlying stop and 2R target are telemetry only.
- Added a first-90-minute failed-level sweep challenger:
  - prior-day high/low and prior-week high/low;
  - sweep beyond a volatility-aware tolerance;
  - close back inside the level;
  - next-bar directional confirmation;
  - next significant level or explicit modeled 2R fallback target.
- Wired both through `strategies/flip_bot.py` into the existing accelerated shadow lifecycle.
- Each signal gets an ATM option contract and entry/mark/exit quote path, but records:
  - `authority=shadow_challenger_only`
  - `execution_enabled=false`
  - `can_submit_orders=false`
  - `live_execution_allowed=false`
- Stable signal IDs prevent repeated monitor scans from counting the same chart trigger as independent trades.
- Existing live 5-minute ORB-retest execution logic is unchanged.

## Analytics Integrity

Research strategies are explicitly isolated in `scripts/flip_shadow_pnl_evaluator.py`:

- `orb_15m_retest`
- `level_sweep_reversal`

They do not contribute to:

- primary `sample_count` or `completed_count`;
- accelerated completion targets;
- symbol EV or symbol promotion;
- challenger leaderboard;
- primary top trades;
- primary time-bucket selector ranking;
- accelerated learning or exit-policy promotion counts;
- the existing 0DTE entry-feature report.

They receive separate `research_strategy_challengers`, `research_top_trades`, and `research_strategy_results` outputs.

## Promotion Contract

Each research strategy needs all of the following before human review:

- 50 completed option lifecycles;
- 10 distinct trading days;
- 15 chronological holdout observations;
- positive full-sample expectancy;
- positive holdout expectancy;
- 100% entry-ask/exit-bid quote coverage;
- explicit human approval.

There is no automatic live promotion.

## Screenshot Claims Accepted or Rejected

Accepted for forward testing:

- ORB breakout, retest, and hold as an independent setup.
- Prior-day and prior-week levels as point-in-time context.
- A failed break plus close-back-inside and next-bar confirmation as a sweep-reversal definition.

Not accepted as evidence:

- the claimed 70% sweep-reversal frequency;
- an unaudited 87% win rate or account challenge;
- one-day 76%-100% option returns;
- adding low-priced tickers merely because contracts appear affordable.

The latter would bypass the system's actual option spread, volume, open-interest, fill-quality, and forward-EV controls. IWM remains excluded from the paper challenger priority because its cumulative shadow EV was negative.

## Registry

Added to `research/signal_registry.json`:

- `flip_15m_orb_retest_shadow_challenger`
- `flip_level_sweep_reversal_shadow_challenger`

The sweep entry records the social 70% claim as explicitly unverified.

## Verification

Focused strategy/analytics suite:

```powershell
python -m pytest agent\tests\test_flip_shadow_setup_challengers.py agent\tests\test_flip_entry_quality.py agent\tests\test_flip_bot_safety.py agent\tests\test_flip_shadow_pnl_evaluator.py agent\tests\test_flip_shadow_time_bucket_report.py agent\tests\test_accelerated_bot_learning_report.py agent\tests\test_flip_exit_policy_comparison.py agent\tests\test_zero_dte_entry_feature_edge_report.py -q
```

Result: `86 passed`.

Governance suite:

```powershell
python -m pytest agent\tests\factors\test_registry.py agent\tests\test_execution_gate_audit.py agent\tests\test_risk_fail_closed_proof.py -q
```

Result: `20 passed`.

Execution audit:

```text
passed=True signals=99 issues=0 warnings=1
```

The warning is the known read-only broker-client verification warning for `portfolio_concentration_monitor.py`.

Risk proof: all four deterministic fail-closed cases passed. The default report temp file was locked on Windows, so Codex reran the same proof with isolated output paths. This was a report-write permission issue, not a failed risk case.

## Next Check

After the next market session, inspect the raw log for `strategy=orb_15m_retest` and `strategy=level_sweep_reversal`, then verify the evaluator shows them only under the research fields. Do not loosen tolerances or promote either strategy from screenshot outcomes.
