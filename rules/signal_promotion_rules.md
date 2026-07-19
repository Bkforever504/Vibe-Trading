# Signal Promotion Rules

Last updated: 2026-07-06

## Core Rule

Signals do not become execution gates because they are interesting. They become gates only after they prove they improve outcomes.

## States

- `context_only`: Logged as market context. No strategy can block or enter trades from it.
- `shadow`: Produces hypothetical entries or holdings. No orders.
- `review`: Summarizes results or risks. No orders.
- `candidate`: Passed initial backtest or forward-test and is awaiting promotion review.
- `execution_gate`: Allowed to influence entry, sizing, or blocking.
- `execution_capable_paper`: Known paper/live-capable bot, guarded by execution controls.

## Promotion Gate

A signal can move from `context_only` or `shadow` to `candidate` only if all are true:

1. At least 30 trading days logged.
2. At least 10 relevant signal/trade samples.
3. Evidence shows improved win rate, profit factor, drawdown, or avoided loss.
4. Evidence does not show overtrading or duplicate exposure.
5. Signal behavior is understandable and reproducible.
6. Codex and Claude both review the evidence.
7. Kenny explicitly approves promotion.

## Accelerated Forward-Evidence Path

Time-bucketed schema-v3 option episodes may reach `candidate` review sooner
than 30 trading days only when all of these stronger volume and holdout rules
are met:

1. At least 100 completed entry-to-exit episodes.
2. At least 10 distinct trading days; same-day episodes never count as extra days.
3. At least 30 newest episodes reserved as a chronological holdout.
4. Positive expectancy in both the pre-holdout history and chronological holdout.
5. Average losses remain controlled relative to average wins after spread/slippage checks.
6. Every episode has a unique lifecycle id, point-in-time reasoning, and explicit exit reason.
7. Repeated snapshots of one episode count as marks, not additional trades.
8. Failures remain in the dataset and all parameter trials enter the immutable trial ledger.
9. Codex and Claude independently review leakage, clustering, regime diversity, and drawdown.
10. Kenny explicitly approves promotion.

This path shortens calendar time to human review. It does not enable live
execution, raise risk, loosen entry gates, or permit a learner to approve its
own strategy changes.

## Execution Gate Requirements

A `candidate` can become an `execution_gate` only if all are true:

1. It has a written rule in the strategy file.
2. It has tests.
3. It has a rollback path.
4. It logs every block/allow decision.
5. It does not bypass `strategies/execution_guard.py`.
6. It cannot enable live trading by itself.
7. It appears in `research/signal_registry.json` with `status=execution_gate`.

## Never Allowed Without Explicit Approval

- Turning on live trading.
- Raising risk per trade.
- Raising max contracts.
- Disabling kill switches.
- Deleting manual-reset files.
- Wiring social, PMXT, X, or copy-trader data directly to orders.
- Treating `possibly_too_strict` as permission to loosen guards.

## Review Cadence

- Daily: read health, leaderboard, daily CSV, bot status, rejected-trade intelligence.
- Weekly: inspect regime memory and overlap reports.
- Monthly: decide whether any signal deserves candidate review.

## Current Position

As of 2026-06-30:

- Market Force Score is observability only.
- Sector Rotation is context only.
- TTM/WaveTrend/SMC are context only.
- Regime Memory is log-building.
- Rejected Trade Intelligence is review only.
- PMXT is manual/read-only and not scheduled.
- Polymarket wallet tracker is review only.
- Cheap Asymmetry Scanner is read-only evidence (added 2026-07-06).

## Cheap Asymmetry Scanner Promotion Criteria

Current state: `review` (read-only, no execution).

To promote to `candidate`:

1. At least 30 trading days of scan data logged.
2. At least 10 completed samples per symbol (entry + exit both known).
3. Repeated `goal_match` hits (cost $10–$50, simulated captured return 500%+).
4. Capture efficiency ≥ 0.5 on average across samples.
5. Options liquidity gate passes for each candidate symbol.
6. No overtrading evidence (same symbol flagged across consecutive days must be reviewed).
7. Dual Claude + Codex review of the evidence log.
8. Kenny explicit approval.

To promote to `execution_gate`:

All candidate requirements above, plus execution gate requirements from the Core Rule above.
Cheap asymmetry contracts must NOT bypass the existing flip bot confidence, spread, and notional guards.
The scanner informs symbol selection — it does not replace the entry stack.
