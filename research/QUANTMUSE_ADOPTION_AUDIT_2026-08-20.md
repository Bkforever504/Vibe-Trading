# QuantMuse Adoption Audit - 2026-08-20

## Decision

Use QuantMuse as an idea catalog. Do not add it as a runtime, backtest, model, or execution dependency.

Audited repository: `0xemmkty/QuantMuse`, commit `f86ede35a81830ab6aded9dc745eb291ccd3efe1`, MIT license.

## Findings

- The local test collection fails because the Binance client is unavailable and `ProcessedData` cannot be imported from the data processor module.
- The backtester does not mark open positions to current market prices. It uses average entry price in its equity calculation.
- Reported win rate counts sell orders instead of profitable closed round trips.
- The execution model does not model bid/ask spread, slippage, latency, partial fills, or point-in-time tradability.
- Strategy optimization is in-sample and lacks walk-forward, purging, embargo, and multiple-testing controls.
- Dependencies are broadly specified rather than pinned, and generated artifacts are committed to the repository.

These issues make the project unsuitable for production trading or profitability validation without a substantial rewrite.

## Adopted Concept

The useful concept is cross-sectional factor agreement: compare each candidate against the other candidates observed in the same market snapshot rather than relying only on fixed indicator thresholds.

The Vibe-Trading radar now records tie-aware percentile ranks for momentum, volume pace, liquidity, spread quality, structure, discovery breadth, and catalyst evidence. It reports:

- weighted consensus score and grade;
- agreement ratio;
- data completeness;
- supporting and conflicting factors;
- cross-section size and formula definition.

This diagnostic is observe-only. It does not change entry gates, sizing, paper eligibility, or order authority. Promotion requires forward outcome evidence demonstrating incremental net expectancy after realistic execution costs.

## Rejected Components

- QuantMuse backtester and performance statistics;
- AI/LLM-generated trading decisions;
- dependency on its strategy optimizer;
- direct reuse of its execution and risk layers;
- claims of production readiness without reproducible verification.
