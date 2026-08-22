# Frozen Strategy Spec — Strategy 1

**Status:** draft
**Kenny Approval:** pending
**Author:** Kenny
**Date:** 2026-08-22
**Spec version:** 1

> Loader activates this spec ONLY when both markers above read `Status: frozen` AND `Kenny Approval: approved`. Until then, this file is scaffolding.

---

## 1. Hypothesis (one sentence)

<!-- Example: "MES 09:32 ET opening-range breakout w/ VIX 15-25 filter has ≥ 55% win rate w/ ≥ 1.5R expectancy over 30d rolling window." -->

TODO Kenny.

## 2. Instrument + Timeframe

- **Symbol:** TODO (SPY / QQQ / IWM / MES / ES / NQ / etc.)
- **Bar TF:** TODO (1m / 5m / 15m / 1h / D)
- **Session:** TODO (RTH only / RTH+ETH / overnight only)

## 3. Entry Rules (deterministic, machine-implementable)

- **Trigger candle:** TODO
- **Volume/RVOL threshold:** TODO
- **Regime filter:** TODO (VIX range? HMM state? Hurst? trend/chop?)
- **Time-of-day filter:** TODO
- **Confluence required:** TODO (any pattern grader detector IDs?)

## 4. Exit Rules

- **Stop:** TODO (ATR multiple? structural level?)
- **T1 target:** TODO
- **T2 target:** TODO
- **Time stop:** TODO
- **Trail rule:** TODO (or "none")

## 5. Position Sizing

- **Risk per trade:** TODO (% of account, must ≤ 25% per bot policy)
- **Max concurrent positions:** TODO
- **Sizing method:** TODO (fixed-fractional / Kelly / etc.)

## 6. Success Gates (promotion criteria)

- Minimum `n_trades`: TODO (default 100)
- Minimum `unique_dates`: TODO (default 30)
- Wilson lower bound win rate: TODO (default 0.55)
- Minimum avg R: TODO (default 1.5)
- Max drawdown tolerance: TODO

## 7. Kill Criteria (demotion / halt)

- Consecutive losses trigger halt: TODO (default 5)
- Rolling 20-trade win rate below: TODO (default 0.40)
- Underwater curve exceeds: TODO (default 15% of high-water mark)

## 8. Data Sources

- **OHLCV:** TODO (Alpaca IEX / Databento MES / etc.)
- **Regime source:** TODO (VIX CBOE / hmm_regime_scanner.py / hurst_regime_scanner.py)
- **Volume boundary:** TODO (RTH vs ETH awareness)

## 9. Backtest Requirements (before flipping to frozen)

- Historical window: TODO (default ≥ 3 years)
- Out-of-sample holdout: TODO (default 6 months)
- Slippage assumption: TODO (ticks or bps)
- Commission model: TODO

## 10. Manual-Only Confirmation

This spec runs shadow-only until Phase 3 promotion. `execution_enabled=false`, `can_submit_orders=false`. Auto-execute requires:
- ≥ 30 shadow trading days
- Success gates §6 met on live shadow log
- Kenny sign-off on `research/STRATEGY_1_PROMOTION_APPROVAL_YYYY-MM-DD.md`

---

**Kenny sign-off (edit both when ready):**

```
Status: frozen
Kenny Approval: approved
```
