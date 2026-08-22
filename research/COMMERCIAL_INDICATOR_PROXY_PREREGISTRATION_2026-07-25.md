# Commercial TradingView Indicator Proxy Lab Preregistration

Date frozen: 2026-07-25

## Purpose

Test whether the publicly described mechanics used by prominent paid
TradingView suites add executable intraday information on SPY and MES.
Protected or invite-only source code will not be copied, inferred, or claimed
to be reproduced. Each family below is an independent implementation of a
published methodology, not the vendor's proprietary indicator.

This is read-only research. It cannot place orders, change production
configuration, schedule a task, or promote a strategy.

## Public Methodology Map

1. `adaptive_trend_pullback`: adaptive average, ATR trend trail, fast-average
   pullback reclaim, and relative volume. This represents the public
   trend-following and reversal-zone concepts described by LuxAlgo and similar
   suites.
2. `oscillator_money_flow`: WaveTrend cross, MFI direction, VWAP side, and
   EMA trend. This represents the public momentum, money-flow, and VWAP
   concepts described by Market Cipher-style suites.
3. `liquidity_structure_reclaim`: prior-20-bar liquidity sweep, close back
   through the level, displacement candle, and relative volume. This
   represents the public liquidity, BOS/CHoCH, and order-block methodology
   described by AlgoAlpha and SMC suites.
4. `multi_oscillator_consensus`: RSI centerline trigger confirmed by MACD,
   stochastic, ADX, and EMA trend. This represents public multi-oscillator
   dashboards such as ChartPrime-style market dynamics.
5. `velocity_ema_ribbon`: 13/48/200 EMA alignment, fast-average slope, ATR
   expansion, and pullback reclaim. This represents public trend-level and
   velocity concepts used by Zeiierman-style suites.
6. `squeeze_release`: Bollinger Bands inside Keltner Channels followed by a
   directional release, volume confirmation, and EMA trend. This represents a
   common premium-suite volatility compression module.

## Data And Execution

- SPY: local Alpaca IEX one-minute underlying bars.
- MES: local one-minute RTH futures bars.
- Only complete 09:30-15:59 ET sessions are accepted.
- Signals use completed real-price five-minute bars.
- One trade per family per session.
- Signal window: 10:00 through 13:30 ET.
- Entry: next five-minute bar open.
- Stop: 1.25 times the completed signal bar's 14-period ATR.
- Target: 1.75R.
- Same-bar stop/target collision: stop first.
- Exit: target, stop, or final RTH bar.
- A next-bar open already beyond the intended stop invalidates the trade.
- SPY costs: one basis point per side.
- MES costs: one tick per side plus $2.48 round-trip commission.
- SPY measures underlying execution only, not option premium, spread, or
  implied-volatility P&L.

## Frozen Indicator Defaults

- EMA: 13, 48, 50, and 200 periods where specified.
- KAMA: efficiency 10, fast 2, slow 30.
- ATR/SuperTrend: ATR 10 and multiplier 3; execution ATR 14.
- Relative volume: current volume / prior-20-bar mean.
- WaveTrend: channel 10, average 21; threshold 40.
- MFI: 14.
- RSI: 14.
- Stochastic: 14, 3.
- MACD: 12, 26, 9.
- ADX: 14 and minimum 20.
- Liquidity lookback: prior 20 bars; displacement body at least 60% of range;
  relative volume at least 1.25.
- Squeeze: Bollinger 20/2 inside Keltner 20/1.5.

No parameter sweep is allowed. A coding correction must be documented and
rerun under the same values.

## Chronological Windows

- Development: 2022-2023.
- Selection: 2024.
- Diagnostic consumed period: 2025 onward.

The 2025+ period has already been inspected elsewhere in this project and is
not a pristine final holdout.

## Metrics And Gates

Report trades, net expectancy in R, win rate, profit factor, maximum drawdown,
moving five-trade block interval, double-cost expectancy, and expectancy after
removing the best 1% of outcomes.

A family is eligible only for a new shadow lane when:

- net expectancy is positive in all three windows;
- selection and 2025+ each contain at least 30 trades;
- 2025+ profit factor is at least 1.20;
- the 2025+ moving-block lower bound is above zero;
- 2025+ expectancy remains positive at double costs;
- 2025+ expectancy remains positive after removing the best 1%; and
- SPY and MES do not materially contradict each other.

Passing permits paper forward observation only. It does not justify live
capital or prove that a paid product itself is profitable.
