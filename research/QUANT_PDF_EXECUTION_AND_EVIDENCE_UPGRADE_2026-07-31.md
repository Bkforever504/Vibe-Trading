# Quant PDF Execution And Evidence Upgrade - 2026-07-31

Purpose: translate durable quant trading literature into controls that improve the current paper-only/shadow-first bot stack without enabling order submission.

## Sources Reviewed

- Almgren and Chriss, "Optimal Execution of Portfolio Transactions"
  - System lesson: execution quality is a measurable cost/risk tradeoff, not an afterthought.
  - Bot upgrade: options shadow twin now measures midpoint credit versus executable sell-bid/buy-ask entry credit.
- AQR, "Transaction Costs: Practical Application"
  - System lesson: separate signal alpha from explicit/implicit trading costs and track transaction-cost drift.
  - Bot upgrade: shadow reports now expose average and worst entry credit lost to bid/ask execution friction.
- Easley, Lopez de Prado, and O'Hara, "The Volume Clock"
  - System lesson: wall-clock time filters are weak unless liquidity/volume context supports them.
  - Bot mapping: time-bucket reports remain research-only and require forward confirmation before any live gate.
- Bailey and Lopez de Prado, "The Deflated Sharpe Ratio"
  - System lesson: best-of-many backtest selections need selection-bias and multiple-testing deflation.
  - Bot upgrade: flip time-bucket rankings now include a multiple-testing haircut and explicit promotion blockers.

## Implemented Controls

- `scripts/options_shadow_twin.py`
  - Adds `execution_cost_quality`.
  - Benchmarks arrival midpoint credit against executable entry credit.
  - Flags incomplete quote coverage and high midpoint-to-executable credit loss.
  - Keeps authority at `shadow_governance_only`.

- `scripts/flip_shadow_time_bucket_report.py`
  - Adds selector trial count.
  - Adds selection-bias haircut per rankable bucket.
  - Adds selection-bias-adjusted expectancy.
  - Adds promotion blockers for small samples, non-positive adjusted expectancy, forward confirmation, and human review.

## Boundaries

- No broker order path was touched.
- No strategy setting was loosened.
- No time bucket, strategy, or symbol can be promoted automatically from these reports.
- The upgrade improves measurement quality; it does not prove profitability.

## Next Evidence Targets

- Resolve at least 30 options shadow twin candidates across at least 20 dates.
- Raise options twin quote evidence from indicative modified quotes toward OPRA NBBO or equivalent executable quote history.
- Compare bucket performance in volume/liquidity regimes before allowing any time filter into live governance.
