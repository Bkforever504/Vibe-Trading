# Preregistration: MES Overnight Drift + VIX Filter

> **Invalidated before forward collection:** the proposed decision time uses
> later 16:00 ET inputs and the hold crosses Topstep's 15:10 CT flatten. The
> corrected causal specification is
> `research/MES_REOPEN_VIX_FILTER_PREREGISTRATION_2026-08-17.md`.

Date: 2026-08-17
Status: frozen. Backtest and honest holdout already run; this freezes the
        implementation before any shadow-log entries are written.
Owner: Claude (shadow-only, no execution)

## Provenance

This is the direct follow-on to:

- research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-08-17.md (SPY, failed)
- research/IWM_OVERNIGHT_PREREGISTRATION_2026-08-17.md (ETF friction killed edge)
- research/mes_overnight_lab.py (full 2022-2026 MES with real Topstep friction)
- research/mes_overnight_holdout.py (train 2022-2024, test 2025-2026-07)

Holdout result (chosen filter selected on train only, evaluated on test only):

| Split | n | Sharpe | Avg $/contract | PF | Max DD $ | Win % |
|-------|---|--------|----------------|-----|----------|-------|
| Train 2022-2024 | 340 | 1.95 | $14.08 | 1.43 | -$695 | ~59 |
| Test 2025-2026-07 | 210 | 1.37 | $12.22 | 1.26 | -$1,493 | 61 |

## Frozen Rule

- Instrument: MES front-month futures (Micro E-mini S&P 500).
- Signal window: US-cash regular-hours close at 16:00 America/New_York.
- Position: LONG one MES contract from 16:00 close of day t to 09:30
  regular-hours open of day t+1. Flat all other times.
- Sizing: exactly one contract per shadow entry. Live sizing not
  authorized by this document.
- Filters (both must be true at entry):
  - VIX close of day t <= 18 (CBOE Volatility Index, yfinance ^VIX).
  - Prior close-to-close percent change of MES front-month
    front-month >= -1.0 % (i.e., yesterday's close did not drop more
    than 1 % vs the day-before close).
- Friction assumption for shadow accounting: 1-tick slippage per side
  ($1.25) + $0.74 commission per side = $3.98 round-trip per contract.

## Evidence Gates (shadow forward test)

- Minimum 30 shadow entries after this freeze date.
- Gate A (proceed to review): median trade P&L > $6.00, win rate
  >= 55 %, max cumulative shadow drawdown > -$3,000 per contract.
- Gate B (promotion review): also require Sharpe > 0.6 on the shadow
  sample and correlation with the backtest daily return series > 0.5.
- Any live-execution proposal requires a separate hand-off document
  and explicit user approval per the repo `execution_change_rule`.

## Kill Conditions (during shadow)

- Shadow drawdown worse than -$3,000 per contract at any time.
- Three consecutive shadow days with realized $ P&L worse than -$40 per
  contract.
- VIX regime shift: five consecutive days with VIX close > 25 flips the
  scanner into "regime-off" mode; shadow entries suspended until VIX
  closes <= 20 again.

## Data / Runner

- Scanner: `strategies/mes_overnight_shadow_logger.py`
- Log: `data/mes_overnight_shadow_log.jsonl`
- Registry: entry `mes_overnight_shadow` in
  `research/signal_registry.json`, state `shadow`,
  `can_submit_orders=false`, `execution_enabled=false`.
- Runner: Windows Task Scheduler at 15:55 America/New_York on trading
  days. Marks entry candidates. Second task at 09:31 America/New_York
  marks realized exit P&L.

## Explicit Limits

- The filter thresholds (VIX <= 18, prior move >= -1 %) are the ones
  selected by the holdout lab's train grid search. No further tuning
  is permitted on the same MES data.
- ETF-based versions (SPY overnight, IWM overnight) are REJECTED and
  must not be promoted from this document.
- No re-fit permitted if shadow evidence fails Gate A or Gate B.
