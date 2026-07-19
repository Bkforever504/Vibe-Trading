# Next-Edge Tests: Overnight Drift and Momentum Forward Refresh

Date: 2026-07-19
Execution state: research only. No execution enabled.

## 1. Overnight Drift (new preregistered family)

Preregistration: `research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-07-19.md`
Script: `research/overnight_drift_lab.py`
Results: `data/overnight_drift_results.json`

Frozen spec: SPY and QQQ, unconditional long close-to-open, no filters,
0.01%/side base cost, sequential dev (2000-2015 in three regimes) ->
selection (2016-2020) -> final (2021+).

- SPY: rejected at development. 2000-2005 mean per-trade return negative
  after costs (-0.00087%/trade, PF 0.996).
- QQQ: passed development (all three regimes positive, PF 1.05-1.14).
  Selection returned +60.4% base / +24.7% at 2x costs, but max drawdown
  -27.8% breached the frozen -25% account-survival gate. Rejected at
  selection. Final period remains untouched.

Verdict: rejected under the frozen specification. Unconditional 100%
allocation every night carries equity-crash drawdowns a $1,000 account
cannot survive. No filters will be added to rescue it on this data.

## 2. Momentum Rotation (frozen candidate, forward evidence refresh)

Script: `research/momentum_rotation_forward_extension.py`
Report: `~/.vibe-trading/reports/momentum-rotation-forward-extension.json`

Frozen 2024 candidate (10-ETF universe, 12-month lookback, top-2, 5-day
rebalance) evaluated on forward data through 2026-07-17:

- Forward 2025+: +51.1% total, PF 3.46, Sharpe 1.57, max DD 12.2%,
  23 trades, 69.6% win rate.
- At doubled costs: +49.0%, PF 3.33.
- 2026 YTD: +8.9%, PF 1.52, max DD 12.2% (weaker than 2025's +38.1%).

This remains the strongest evidence-backed systematic lane in the project.
Caveats: yfinance adjusted data is not venue-executable; the 2025+ window is
now consumed evidence and cannot be called untouched again; 23 forward trades
is below the 30-trade promotion gate.

## 3. ICT/SMC Family: Liquidity-Sweep Fade and FVG Continuation (rejected)

Preregistration: `research/MES_SMC_PREREGISTRATION_2026-07-19.md`
Script: `research/mes_smc_lab.py`
Results: `data/mes_smc_results.json`

Six frozen configurations on the corrected MES 1m data (803 development
sessions, three regimes, sequential gating). All six failed at development;
selection and final data were never touched.

- Sweep fade (prior-day high/low break + reclaim): development expectancy
  -$3.33 to -$3.98/trade, PF 0.88-0.89 across 323 trades. Negative in the
  2024+ regime especially (PF ~0.74).
- FVG continuation (5m imbalance, midpoint entry): the best variant
  (gap >= 4 ticks, 1.5R) was positive in two of three regimes but negative
  in the most recent regime (PF 0.94), failing the all-regimes gate.
  Larger-gap variants were negative outright.

Verdict: the mechanically testable cores of "liquidity sweeps" and "fair
value gaps" show no stable edge on MES under realistic costs. The social
popularity of these concepts is not supported by this data. No filters will
be added to rescue them.

## Ranking After These Tests

1. Momentum rotation: continue accumulating forward trades toward the
   30-trade gate. No parameter changes.
2. IWM options premium lanes: forward paper evidence only.
3. Overnight drift: rejected.
4. MES intraday: paused, dataset consumed.
5. QQQ RSI2: frozen, awaiting forward data.

No strategy tested today qualifies for live capital. Promotion still requires
the full gate stack plus Kenny's explicit approval.
