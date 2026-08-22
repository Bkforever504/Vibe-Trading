# Indicator Recipe Lab Preregistration

Date frozen: 2026-07-25

## Purpose

Test whether four popular TradingView concepts add executable information to
SPY and MES intraday price action:

1. New York AM "killzone" timing.
2. Prior-session floor pivots and prior-day high/low.
3. A mechanically defined Failed 2 reversal trigger.
4. Heikin-Ashi trend state, session VWAP, and point-in-time daily/weekly trend.

This is read-only research. It cannot place orders, alter production settings,
enable a scheduler, or promote a strategy.

## Data

- SPY: local Alpaca IEX one-minute underlying bars.
- MES: local one-minute RTH futures bars.
- Only complete 09:30-15:59 ET sessions are accepted.
- All signal calculations use information available before entry.
- SPY results measure underlying price, not option premiums or fills.

## Fixed Trigger

Bars are aggregated to real-price five-minute candles.

- Bearish Failed 2: an attempted 2-up bar exceeds the prior bar high without
  breaking its low, then the next completed bar closes below the attempt low.
- Bullish Failed 2: mirror image.
- Entry: next five-minute bar open.
- Stop: one tick beyond the larger extreme of the attempt and confirmation
  bars.
- Target: 1.5R.
- Exit: target, stop, or final RTH bar.
- Same-bar target/stop ambiguity is resolved as a stop.
- Maximum one trade per variant per session.
- Trades with risk below two ticks or above 25% of the prior RTH range are
  rejected.

## Context Definitions

- Killzone: Failed 2 confirmation completes from 09:35 through 10:59 ET, so
  entry occurs no later than 11:00.
- Pivot location: the attempt wick breaches and closes back through at least
  one of prior-day high, prior-day low, traditional pivot P, R1, or S1. The
  breach may not exceed 5% of the prior-day range beyond the level.
- Heikin-Ashi: two completed 15-minute HA candles agree with trade direction.
  HA is calculated only as a state filter. Entries, stops, targets, and P&L use
  real OHLC.
- VWAP: confirmation close is above session VWAP for longs and below for
  shorts.
- HTF non-opposed: point-in-time daily and weekly states may be aligned or
  mixed, but neither may oppose the trade. Daily uses a 20-session SMA and
  five-session slope; weekly uses a 20-week SMA and five-week slope. Only
  periods completed before the session are eligible.

## Fixed Variants

1. `failed2_raw`
2. `failed2_killzone`
3. `failed2_pivot`
4. `failed2_pivot_killzone`
5. `failed2_pivot_killzone_ha`
6. `failed2_pivot_killzone_vwap`
7. `full_recipe`

`full_recipe` requires Failed 2, pivot location, killzone, HA, VWAP, and HTF
non-opposition. No variants or thresholds may be added after results are seen.

## Costs And Windows

- SPY: one basis point of slippage per side.
- MES: one tick of slippage per side plus $2.48 round-trip commission.
- Development: 2022-2023.
- Selection: 2024.
- Diagnostic consumed period: 2025 onward.
- Report gross and net expectancy, profit factor, win rate, target rate,
  maximum drawdown, moving-block interval, double-cost expectancy, and
  expectancy after removing the best 1% of outcomes.

## Gates

A variant is only eligible for a new shadow lane when:

- net expectancy is positive in all three chronological windows;
- selection and 2025+ each contain at least 30 trades;
- 2025+ profit factor is at least 1.20;
- the 2025+ moving-block lower bound is above zero;
- 2025+ expectancy remains positive at double costs;
- 2025+ expectancy remains positive after removing the best 1%; and
- no material contradiction appears between SPY and MES.

Passing these gates would permit paper forward-testing only. The data and
2025+ period have already been consumed by prior project research.
