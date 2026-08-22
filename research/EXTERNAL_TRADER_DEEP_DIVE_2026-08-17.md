# External Trader and Algorithm Research Deep Dive

Date: 2026-08-17

## Question

Can the system learn from traders with proven records, books, YouTube, open-source engines, and public strategies without importing selective marketing claims or unsafe execution authority?

## Answer

Yes, through three separate lanes:

1. **Exact public rules** become frozen, cost-aware shadow replications.
2. **Verified but opaque records** are discovery evidence only. They can teach risk process, but their entries cannot be copied or inferred.
3. **Books, videos, and frameworks** become process controls unless their rules and data are independently reproducible.

No source can promote itself to paper or live trading.

## Strongest Findings

### 1. Medium-horizon momentum and diversified trend deserve continued testing

- AQR's century study and the original time-series momentum paper document trend behavior across equity index, bond, currency, and commodity futures.
- Jegadeesh and Titman provide the canonical cross-sectional winner-minus-loser evidence.
- The evidence is not uncontested. Huang, Li, and Zhou argue much of time-series momentum may resemble the assets' unconditional mean returns. Every trend result must therefore be compared with long-only and matched-volatility benchmarks.

Primary sources:

- https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing
- https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
- https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1993.tb04702.x
- https://doi.org/10.1016/j.jfineco.2019.08.004

Implementation: `research/pyquant_strategy_family_lab.py` now includes a labeled smooth-momentum proxy. It prefers persistent positive returns over a single jump, executes one day after signal formation, charges turnover, doubles costs in stress, and remains shadow-only.

### 2. Short-volatility needs an honest benchmark, not a high win rate

Cboe publishes exact PutWrite index mechanics, including option selection, collateral, and pricing windows. The index is an appropriate benchmark for the options stack, but it is not a retail fill record and its pre-2007 history is backtested.

Primary sources:

- https://cdn.cboe.com/api/global/us_indices/governance/Cboe_SP_500_PutWrite_Indices_Methodology.pdf
- https://cdn.cboe.com/resources/indices/factsheet/CboeGlobalIndices_PUT-Index.pdf

Sinclair's framework reinforces the repo's current direction: compare maturity-matched ATM implied volatility with a forward realized-volatility estimate after spread friction and event risk. IV rank alone is not an edge estimate.

- https://onlinelibrary.wiley.com/doi/book/10.1002/9781118662724

Implementation: Cboe is registered as a benchmark. The volatility-premium report is registered as a process control. The Milkman ATR spread remains hypothesis-only because executable historical SPX option quotes are still missing.

### 3. Execution realism is more transferable than another indicator

QuantConnect's official LEAN documentation explicitly separates slippage, fill, fee, stale-data, and live reconciliation models. A zero-slippage or immediate-fill default can materially overstate an edge.

Primary sources:

- https://github.com/QuantConnect/Lean
- https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts
- https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/reconciliation

Implementation: the existing limit-execution lab and execution-seasonality report are now registered as required engineering controls for all bots.

### 4. Portfolio risk controls are teachable even when entries are proprietary

Carver's process combines forecast scaling, volatility targeting, diversification, and turnover costs. Darwinex documents risk normalization and correlated-position leverage controls. Sersan's public pages and Darwinex interview provide a potentially verified record, but exact entry rules remain proprietary and therefore cannot be copied.

Primary sources:

- https://www.harriman-house.com/systematic-trading
- https://github.com/pst-group/pysystemtrade
- https://help.darwinex.com/risk-adjustment-attribute
- https://www.sersansistemas.com/syo-preguntas-y-respuestas/
- https://music.youtube.com/podcast/hYzRW3LsLzw

Implementation: clustered portfolio Monte Carlo is registered as an adopted process control. Sersan/Darwinex is discovery-only.

## YouTube, Reddit, and X

The last-30-days scan covered Reddit, Hacker News, X, and YouTube. It found useful warnings about uncovered option tail risk and cost leakage, but no current YouTube result with exact rules, complete losses, independently verified fills, and sufficient holdout evidence. Social sources remain idea discovery only.

Required intake standard for a trader record:

- Broker export or platform-verified complete history
- At least 100 trades and 60 calendar days
- Deposits and withdrawals separated from P&L
- Visible contracts, timestamps, fills, fees, and losses
- Profit factor at least 1.30 after costs and delay
- Maximum drawdown at most 15%
- At least 95% defined-risk trades for options
- Explicit consent for ingestion or copying

## New Challenger Result

`quality_momentum_smooth_12m_top2_monthly_proxy` on the repo's canonical ETF universe, 2007-01-03 through 2026-08-14:

- CAGR: 12.23%
- Sharpe: 0.744
- Maximum drawdown: 32.35%
- Selection CAGR (2022-2024): 8.76%
- Final CAGR (2025 onward): 21.14%
- Double-cost CAGR: 11.79%
- Existing shadow-review gate: passed

This is not a production result. The proxy's drawdown is worse than the existing weekly canonical strategy's 24.83%, the universe is small, and the test uses current ETF history rather than a point-in-time stock universe. It stays a shadow challenger.

## Current System Evidence

The combined profitability report remains blocked:

- Resolved options observations: 16
- Active resolution days: 5
- Aggregate executable P&L before fees: -$569
- Minimum 30-observation gates: not met
- Clustered portfolio history: insufficient

Outside teachings improve the experiment pipeline. They do not justify overriding this evidence.

## Next Experiment

1. Apply the already validated breadth/BIL cash overlay to the smooth-momentum challenger.
2. Freeze the rules before rerunning; compare Calmar, final-window return, turnover, and double-cost performance.
3. Start a monthly forward shadow ledger with source timestamps and one-trading-day execution lag.
4. Require at least 12 resolved monthly rotations before review and 24 before any paper-promotion discussion.
5. Keep options source hypotheses blocked until exact executable quote histories are available.

## Files

- Registry: `research/external_strategy_sources.json`
- Audit code: `scripts/external_strategy_evidence.py`
- Audit output: `data/external_strategy_evidence_report.json`
- Human report: `research/EXTERNAL_STRATEGY_EVIDENCE_REPORT_2026-08-17.md`
- Strategy challenger: `research/pyquant_strategy_family_lab.py`
- Combined review: `scripts/profitability_evidence_review.py`

Execution enabled: false  
Can submit orders: false  
Automatic promotion: false
