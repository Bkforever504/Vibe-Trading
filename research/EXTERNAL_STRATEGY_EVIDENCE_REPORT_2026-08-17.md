# External Strategy Evidence Report

As of: 2026-08-17

This report separates reproducible teachings from marketing claims. It has no execution or promotion authority.

| Source | Role | Score / 10 | Classification | Bot use |
|---|---:|---:|---|---|
| Cboe S&P 500 PutWrite Index Methodology | benchmark | 8.60 | benchmark_accepted | options_stack |
| A Century of Evidence on Trend-Following Investing | research_hypothesis | 8.15 | shadow_replication_eligible | swing_cash_sleeve |
| Returns to Buying Winners and Selling Losers | research_hypothesis | 8.07 | shadow_replication_eligible | swing_cash_sleeve |
| Time Series Momentum: Is It There? | falsification_evidence | 7.80 | required_caveat | research_pipeline |
| Alpha Architect Quantitative Momentum Methodology | research_hypothesis | 7.02 | hypothesis_only | swing_cash_sleeve |
| Robert Carver Systematic Trading and pysystemtrade | process_control | 7.80 | process_control_adopted | portfolio_governor |
| QuantConnect LEAN Reality Modeling | engineering_reference | 8.30 | engineering_reference | all_bots |
| Euan Sinclair Volatility Trading | process_control | 7.25 | process_control_adopted | options_stack |
| Ernest Chan Algorithmic Trading and Quantitative Trading | process_control | 7.48 | process_control_adopted | research_pipeline |
| Darwinex Risk Engine and Sersan Sistemas Public Record | verified_track_record_discovery | 6.22 | discovery_only | portfolio_governor |
| Milkman Trades Weekly SPX -1 ATR Put Spread | research_hypothesis | 5.95 | hypothesis_only | options_stack |
| Social Media P&L Screenshots and Selective Trade Posts | social_claim | 0.65 | rejected_as_edge_evidence | verified_trader_pipeline |

## Governance

- Social screenshots, testimonials, and selective trade posts are rejected as edge evidence.
- Opaque but broker-verified track records may identify candidates, never rules to copy.
- Exact public rules may enter a cost-aware shadow replay only after the declared implementation artifact exists.
- Books and videos are process education unless their rules and data are reproducible.
- Every eligible hypothesis remains blocked from paper or live promotion by this report.

## Current Actions

- **Cboe S&P 500 PutWrite Index Methodology**: Benchmark short-volatility systems against collateralized, mechanically priced put writing.; Use a documented quote window and collateral return instead of assuming midpoint fills.
- **A Century of Evidence on Trend-Following Investing**: Diversified trend signals are more defensible across markets and horizons than one intraday breakout rule.; Volatility scaling and portfolio diversification are part of the strategy, not optional packaging.
- **Returns to Buying Winners and Selling Losers**: Measure medium-horizon relative strength and execute after signal formation.; Expect momentum crashes and long drawdowns; use cash and breadth overlays rather than tight per-trade stops.
- **Robert Carver Systematic Trading and pysystemtrade**: Forecast scaling, volatility targeting, diversification, and trading costs must be modeled together.; Slow the strategy when turnover costs consume the forecast.
- **QuantConnect LEAN Reality Modeling**: Backtests must use explicit slippage, fees, stale-quote handling, and order-state reconciliation.; A zero-slippage default is a configuration hazard, not a conservative assumption.
- **Euan Sinclair Volatility Trading**: Compare maturity-matched implied volatility with a forward realized-volatility forecast net of friction.; Measure edge after skew, event risk, transaction costs, and position sizing.
- **Ernest Chan Algorithmic Trading and Quantitative Trading**: Separate development, selection, and final test data and include realistic trading costs.; Prefer simple rules that survive walk-forward and parameter perturbation.

## Safety

Execution enabled: `false`  
Can submit orders: `false`  
Automatic promotion: `false`
