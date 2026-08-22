# SwiftCap X-PDBO Source Audit - 2026-08-14

## Verdict

The public download is readable MQL5 source, not a compiled black box. It is
also explicitly labeled AI-generated and unfinished. It must remain a research
hypothesis until a source-matched transfer test survives costs and sealed data.

## Mechanical Rules Reconstructed

- First bar check beyond the previous broker-day high or low.
- Trade only when completed daily ATR(5) is below ATR(10).
- One trade per server day; whichever direction appears first wins.
- Default stop is the opposite side of the previous day's range.
- Default target is 3R.
- Default exit closes at 22:50 broker-server time.
- Position size targets a fixed account-currency loss.

## Source-Level Risks

1. The code comment says "crosses," but implementation only checks the first
   tick of each chart bar. Results therefore depend on the chart timeframe,
   which the download page does not specify.
2. No trading session is defined. Previous-day levels and the end-of-day exit
   depend on broker server time and can differ across brokers.
3. Restarting MetaTrader loses the in-memory one-trade-per-day and entry state.
   A same-day re-entry or disabled safety exit can follow a restart.
4. End-of-day closure requires the configured hour to match exactly. If the
   terminal misses that hour, the position may remain open.
5. Invalid tick metadata falls back to a non-zero 0.01 lot rather than blocking.
6. There is no spread, news, stale-price, margin, or market-session gate.
7. A market order is sized and bracketed from the observed ask/bid even though
   the actual fill may differ.
8. The unused `prevClose` and naming (`UJ_Breakout`) indicate prototype code.

## Repository Decision

Do not install or execute the EA. The source-matched lab tests the strategy on
one-contract MES using RTH levels, Wilder ATR, explicit fees/slippage, adverse
same-bar ordering, three chronological windows, double costs, and top-1% winner
removal. No result can change live gates or submit orders.

## MES Transfer Result

The 2022-2026 replay covered 1,148 RTH sessions and produced zero survivors.
The closest source-faithful 5-minute variant earned $5.43 per trade over the
whole sample, but lost $15.25 per trade in the 2025 selection window. Its
expectancy fell to $0.45 under doubled costs and to -$0.46 after removing the
largest one percent of winners. The 1-minute and 15-minute variants failed the
same robustness checks. The no-ATR-filter control lost $3.85 per trade overall.

An initially strong intrabar-cross result was a backfill artifact on gap days.
Using the session open instead of yesterday's stale breakout level removed the
artifact; the corrected variant lost $13.40 per trade in 2025 and also failed
the top-one-percent-winner test.
