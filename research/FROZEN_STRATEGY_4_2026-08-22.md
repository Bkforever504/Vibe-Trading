# Frozen Strategy Spec — Strategy 4

**Status:** draft
**Kenny Approval:** pending
**Author:** Kenny
**Date:** 2026-08-22
**Spec version:** 1

> Loader activates this spec ONLY when both markers above read `Status: frozen` AND `Kenny Approval: approved`.

---

## 1. Hypothesis (one sentence)

TODO Kenny.

## 2. Instrument + Timeframe

- **Symbol:** TODO
- **Bar TF:** TODO
- **Session:** TODO

## 3. Entry Rules

- **Trigger candle:** TODO
- **Volume/RVOL threshold:** TODO
- **Regime filter:** TODO
- **Time-of-day filter:** TODO
- **Confluence required:** TODO

## 4. Exit Rules

- **Stop:** TODO
- **T1 target:** TODO
- **T2 target:** TODO
- **Time stop:** TODO
- **Trail rule:** TODO

## 5. Position Sizing

- **Risk per trade:** TODO
- **Max concurrent positions:** TODO
- **Sizing method:** TODO

## 6. Success Gates

- Minimum `n_trades`: TODO
- Minimum `unique_dates`: TODO
- Wilson lower bound win rate: TODO
- Minimum avg R: TODO
- Max drawdown tolerance: TODO

## 7. Kill Criteria

- Consecutive losses: TODO
- Rolling 20-trade win rate below: TODO
- Underwater curve exceeds: TODO

## 8. Data Sources

- **OHLCV:** TODO
- **Regime source:** TODO
- **Volume boundary:** TODO

## 9. Backtest Requirements

- Historical window: TODO
- Out-of-sample holdout: TODO
- Slippage assumption: TODO
- Commission model: TODO

## 10. Manual-Only Confirmation

`execution_enabled=false`, `can_submit_orders=false` until Phase 3 promotion.

---

**Kenny sign-off:**

```
Status: frozen
Kenny Approval: approved
```
