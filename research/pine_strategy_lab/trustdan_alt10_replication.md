# Trustdan Alt10 Replication

Date: 2026-06-28

Source:
`research/pine_sources/trustdan-trend-following/pine-scripts/14_PF-1.232_SPY_seykota_alt10_profit_targets.pine`

Python replication:
`research/trustdan_alt10_backtest.py`

Decision: rejected for bot promotion until better data reproduces the edge.

## Why This Needed A Dedicated Backtester

Alt10 is not a simple long/flat signal strategy. It uses:

- Donchian 55-bar breakout entries.
- ATR/N unit sizing.
- Pyramiding up to 4 units.
- Add-ons every 0.5N.
- Partial exits at 3N, 6N, and 9N.
- Chandelier stop on the remaining position.

The normal Pine Strategy Lab signal backtester cannot model partial scale-outs, so Alt10 was implemented as a standalone event simulator that tracks closed legs.

## Trustdan Claim

Trustdan's docs report Alt10 as the top universal strategy:

- 76.19% success rate.
- 16/21 tickers profitable.
- 2-hour data.
- Frequent exits suitable for options.

## Independent Daily-Bar Replication

Window: 2015-01-01 to 2024-12-31  
Symbols: UNH, XLV, CAT, PLD, XLF, XLE, XLP, SPY, QQQ, MSFT, AMZN, WMT, GOOGL

| Symbol | Return | PF | WR% | DD | Trades | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| UNH | -30.85% | 0.70 | 32.6% | 48.6% | 181 | -0.32 |
| XLV | -3.81% | 0.97 | 33.0% | 32.5% | 194 | 0.02 |
| CAT | -16.49% | 0.86 | 32.9% | 41.0% | 222 | -0.11 |
| PLD | -5.30% | 0.94 | 35.4% | 31.1% | 198 | 0.01 |
| XLF | -13.13% | 0.88 | 32.4% | 37.2% | 210 | -0.07 |
| XLE | -21.88% | 0.77 | 35.7% | 32.4% | 221 | -0.17 |
| XLP | -35.45% | 0.60 | 29.9% | 38.1% | 194 | -0.36 |
| SPY | +25.39% | 1.23 | 37.1% | 30.8% | 213 | 0.25 |
| QQQ | +59.62% | 1.45 | 45.3% | 29.0% | 214 | 0.44 |
| MSFT | +76.32% | 1.68 | 44.5% | 17.6% | 182 | 0.54 |
| AMZN | +28.75% | 1.20 | 41.5% | 24.2% | 217 | 0.27 |
| WMT | +0.33% | 1.00 | 34.6% | 40.5% | 205 | 0.06 |
| GOOGL | +12.24% | 1.13 | 35.2% | 18.8% | 193 | 0.16 |

Profitable: 6/13.

## Source-Default Window Replication

The Pine file defaults `fromDate` to 2022-01-01, so the same symbols were rerun on 2022-01-01 to 2024-12-31.

Profitable: 5/13.

Best rows:

- SPY: +17.17%, PF 1.76, DD 17.3%, 50 trades.
- WMT: +15.46%, PF 1.56, DD 25.5%, 61 trades.
- QQQ: +13.29%, PF 1.50, DD 13.0%, 56 trades.

Healthcare did not reproduce:

- UNH: -23.32%, PF 0.22, DD 28.8%.
- XLV: -21.58%, PF 0.34, DD 24.8%.

## 2-Hour Approximation

Trustdan used 2-hour data. Because free yfinance intraday history is limited, we approximated 2-hour bars by pairing recent 1-hour bars from the last ~730 days.

Profitable: 5/13.

Best rows:

- MSFT: +18.47%, PF 1.22, DD 29.3%, 189 trades.
- CAT: +17.04%, PF 1.12, DD 27.5%, 240 trades.
- PLD: +10.81%, PF 1.09, DD 37.0%, 167 trades.

Weak rows:

- XLP: -42.00%, PF 0.61, DD 58.0%.
- AMZN: -38.45%, PF 0.55, DD 44.0%.
- XLE: -32.99%, PF 0.70, DD 43.7%.

## Interpretation

Alt10 did not pass our independent replication standard.

Likely causes:

- Trustdan's exact 2-hour TradingView bars may differ from yfinance-resampled bars.
- TradingView fill semantics for pyramids and partial exits differ from this event simulator.
- Trustdan's source results may depend on a specific period, data vendor, or symbol universe.
- The strategy has high trade frequency, so small differences in fill order and bar construction matter.

This is still useful research: profit-target/pyramid mechanics are worth studying, but Alt10 itself should not be promoted to paper execution until it reproduces on our data.

## Current Ranking

1. Momentum rotation top-2 weekly: paper candidate.
2. RSI-2 QQQ mean reversion: shadow/paper-forward candidate.
3. Trustdan Alt10: rejected pending exact 2-hour data replication.
4. Alorse MACD + BB + RSI: rejected, low sample.
5. Alorse RSI + EMA: rejected, drawdown/short-side issue.

## Next Action

Test Trustdan Alt45 or Alt26 only after deciding whether to:

1. Add exact 2-hour historical data from a better source, or
2. Restrict trustdan candidates to daily-bar-compatible variants.

Do not wire Alt10 to any trading bot.
