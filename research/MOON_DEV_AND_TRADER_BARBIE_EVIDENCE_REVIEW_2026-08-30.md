# Moon Dev backtest claims and STRAT/SMC/ICT checklist review

## Scope

The supplied screenshots show Moon Dev continuation-agent headline backtests
and a Trader Barbie description of a STRAT/SMC/ICT “cocktail” using 50% CE,
BSL/SSL, and 15-minute support/resistance. This is a research review, not a
performance endorsement.

## Primary-source findings

- Moon Dev describes its AI-agent trading project as experimental and explicitly
  says it is not a profitable or plug-and-play trading system. See the project
  README: https://github.com/daydy-dev/moon-dev-ai-agents
- Moon Dev’s public battle benchmark says all models receive identical hourly
  snapshots and decisions are evaluated publicly, but also warns that the
  experiment is not a strategy or investment advice and is intentionally risky:
  https://github.com/moondevonyt/Moon-Dev-AI-Trading-Battles
- Moon Dev’s API documentation is primarily for Hyperliquid and Polymarket
  data (liquidations, positions, trades, and order flow), not OPRA SPY options:
  https://moondev.com/docs

## Interpretation of the screenshots

The displayed returns (including a six-figure percentage) are not evidence of
transferable edge by themselves. Before considering any strategy, we need the
exact data interval, leverage, compounding convention, position sizing,
commission/slippage, delisted-symbol handling, timestamp alignment, and an
untouched test period. A table showing return, Sharpe, win rate, and max drawdown
without those controls can be dominated by overfitting or unrealistic fills.

## What is worth testing from the Barbie framework

Translate terminology into observable fields only:

1. higher-timeframe liquidity level (BSL/SSL or prior swing),
2. sweep and close-back-inside confirmation,
3. 50% equilibrium/CE location within a defined dealing range,
4. 15-minute support/resistance confluence,
5. 3-minute/5-minute execution confirmation,
6. fixed invalidation and staged targets.

These should be logged as shadow features and compared with the current A+
stack. They must not be added as independent score points until they improve
out-of-sample recall, ranking regret, and net-after-costs outcomes across dates
and regimes.

## Recommended disposition

- Do not import Moon Dev code or headline parameters into production.
- Use its reproducible snapshot/backtest idea as a benchmark design pattern:
  frozen inputs, identical snapshots, explicit skip decisions, and public
  decision/equity logs.
- Add Barbie-style liquidity/CE fields as a shadow challenger. Keep the feature
  rank-neutral until at least five independent trading sessions and a held-out
  validation period are complete.
- Keep all outputs execution-disabled and fail-closed when data quality or
  causal timestamps are missing.
