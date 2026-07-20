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

## 4. VWAP Band Fade on Classified Range Days (rejected)

Preregistration: `research/MES_VWAP_FADE_PREREGISTRATION_2026-07-19.md`
Script: `research/mes_vwap_fade_lab.py`
Results: `data/mes_vwap_fade_results.json`

The one genuinely untested candidate from the course-intelligence intake,
also independently suggested in the Codex handoff. Four frozen configs
(band 1.0/1.5 sigma x wick 0/2 ticks) with a causal trend-day filter,
dynamic VWAP target, 32-tick stop, 60-minute time stop.

All four failed development across all regimes: expectancy -$3.55 to
-$7.94/trade, profit factors 0.38-0.51 on 499-756 trades. Win rates
(44-57%) fall far short of the course's claimed 70-80%, and the structure
is reward-starved: the VWAP target pays a fraction of the 8-point stop, so
even the claimed hit rate would not produce positive expectancy after
costs. Selection and final periods never touched.

Verdict: rejected. This closes the course canon - every mechanically
testable entry concept from the top YouTube course material is now either
tested-and-rejected, already deployed, or frozen awaiting forward data.

## 5. Turn-of-Month Effect (SPY passes all historical gates; QQQ rejected)

Preregistration: `research/TURN_OF_MONTH_PREREGISTRATION_2026-07-19.md`
Script: `research/turn_of_month_lab.py`
Results: `data/turn_of_month_results.json`

One frozen rule, zero parameters searched: long SPY from the close of the
5th-to-last trading day of the month through the close of the 3rd trading
day of the next month; flat otherwise.

- Development 2000-2015: positive in all three regimes (+34.6%, +48.9%,
  +39.9%), including 2000-2005 when buy-and-hold lost 6.2%.
- Selection 2016-2020: +63.6%, PF 1.40, max DD -8.8%; +61.7% at 2x costs.
- Final 2021+: +19.3%, PF 1.12, max DD -15.6%; positive at 2x and 3x
  costs. All final gates pass.
- QQQ: rejected at development (2000-2005 negative).

Honest caveats: the effect is weakening (final PF 1.12 vs selection 1.40);
final-period return is well below buy-and-hold (+19.3% vs +114.1%) - this
is a low-exposure (roughly one-third time in market) overlay, not a
beat-the-market machine; the anomaly is widely published, so continued
decay is the base case. Per the preregistration, this pass permits paper
forward-testing only.

On the $1,000 model it contributes roughly $40-50/year at the recent pace.
Its value is as an uncorrelated overlay that leaves the account in cash
two-thirds of the time, potentially stackable with the momentum lane.

## Ranking After These Tests

1. Momentum rotation: continue accumulating forward trades toward the
   30-trade gate. No parameter changes.
2. IWM options premium lanes: forward paper evidence only.
3. Overnight drift: rejected.
4. MES intraday: paused, dataset consumed.
5. QQQ RSI2: frozen, awaiting forward data.

No strategy tested today qualifies for live capital. Promotion still requires
the full gate stack plus Kenny's explicit approval.
