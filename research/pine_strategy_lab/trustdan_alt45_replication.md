# Trustdan Alt45 Replication
Date: 2026-06-28
Source: `research/pine_sources/trustdan-trend-following/pine-scripts/seykota_alt45_dual_momentum_confirmation.pine`
Python replication: `research/trustdan_alt45_backtest.py`

## Alt45 vs Alt10

Alt45 adds RSI(14) > 50 dual-momentum gate to the Alt10 Donchian entry.
Age-based targets: Young ≤15 bars → 4N/7N/10N, Mature ≤30 bars → 3N/6N/9N, Aging → 2N/4N/6N.

## Trustdan Claim

- 66.67% success rate (14/21 tickers profitable)
- Daily data, ~2010-2025

## Independent Daily-Bar Replication (2015-2024)

| Symbol | Return | PF | WR% | DD | Trades | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| UNH | -32.48% | 0.69 | 33.7% | 49.2% | 187 | -0.35 |
| XLV | -5.22% | 0.96 | 33.8% | 33.2% | 195 | 0.01 |
| CAT | -17.46% | 0.84 | 33.8% | 41.8% | 222 | -0.12 |
| PLD | -13.23% | 0.85 | 35.9% | 33.7% | 198 | -0.07 |
| XLF | -9.67% | 0.91 | 34.5% | 35.3% | 209 | -0.03 |
| XLE | -24.51% | 0.75 | 33.5% | 33.8% | 221 | -0.20 |
| XLP | -36.10% | 0.61 | 29.0% | 38.6% | 200 | -0.37 |
| SPY | +15.12% | 1.14 | 37.0% | 32.0% | 219 | 0.18 |
| QQQ | +55.96% | 1.42 | 45.2% | 29.0% | 219 | 0.42 |
| MSFT | +80.56% | 1.73 | 46.5% | 18.0% | 187 | 0.56 |
| AMZN | +28.00% | 1.19 | 42.2% | 25.6% | 218 | 0.26 |
| WMT | -2.42% | 0.98 | 34.6% | 41.2% | 211 | 0.03 |
| GOOGL | +9.18% | 1.09 | 35.6% | 18.7% | 194 | 0.13 |

Profitable: 5/13.

## Independent Daily-Bar Replication (2022-2024)

| Symbol | Return | PF | WR% | DD | Trades | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| UNH | -24.02% | 0.20 | 21.6% | 28.9% | 51 | -1.05 |
| XLV | -22.48% | 0.33 | 22.0% | 25.7% | 59 | -0.83 |
| CAT | +4.34% | 1.15 | 42.6% | 11.6% | 68 | 0.18 |
| PLD | -4.20% | 0.85 | 41.7% | 13.3% | 60 | -0.08 |
| XLF | -0.23% | 0.99 | 27.6% | 19.4% | 58 | 0.05 |
| XLE | -6.58% | 0.76 | 26.5% | 15.5% | 49 | -0.20 |
| XLP | -15.17% | 0.49 | 25.0% | 19.8% | 60 | -0.46 |
| SPY | +14.79% | 1.60 | 39.6% | 17.3% | 53 | 0.45 |
| QQQ | +9.82% | 1.38 | 46.4% | 13.4% | 56 | 0.32 |
| MSFT | -0.69% | 0.98 | 35.2% | 15.8% | 54 | 0.04 |
| AMZN | -15.21% | 0.49 | 34.5% | 19.8% | 58 | -0.44 |
| WMT | +15.22% | 1.54 | 41.3% | 25.1% | 63 | 0.45 |
| GOOGL | -6.88% | 0.74 | 30.0% | 13.9% | 60 | -0.15 |

Profitable: 4/13.

## Alt10 vs Alt45 Comparison (2015-2024)

| Symbol | Alt10 PF | Alt45 PF | Delta |
|---|---:|---:|---:|
| SPY | 1.23 | 1.14 | -0.09 |
| QQQ | 1.45 | 1.42 | -0.03 |
| MSFT | 1.68 | 1.73 | +0.05 |
| AMZN | 1.20 | 1.19 | -0.01 |
| GOOGL | 1.13 | 1.09 | -0.04 |
| UNH | 0.70 | 0.69 | -0.01 |
| XLV | 0.97 | 0.96 | -0.01 |

The RSI filter is neutral-to-slightly-negative: profitable symbols stay profitable, unprofitable stay unprofitable. The RSI gate does not fix the underlying data-vendor gap.

## Interpretation

Alt45 did not pass independent replication. Profitable rate: 5/13 (38.5%) vs trustdan's claim of 66.67% (14/21).

The RSI dual-momentum filter does not improve results vs Alt10 on daily yfinance data. The same 5 symbols are profitable in both strategies (SPY, QQQ, MSFT, AMZN, GOOGL — all tech/growth with strong secular trends). Healthcare (UNH, XLV), commodities (XLE), and defensive sectors (XLP) remain unprofitable.

Probable causes (same as Alt10):
- Trustdan's TradingView bar construction differs from yfinance daily adjusted bars.
- ATR-sized stops and pyramiding are extremely sensitive to exact bar high/low data.
- Age-based target tightening (the Alt45-specific feature) doesn't compensate for entry-timing differences caused by the data gap.

## Decision

Rejected for bot promotion. Same root cause as Alt10 rejection.

The SPY/QQQ subset does show consistent positive PF (1.14–1.60) across both windows. If exact TradingView-equivalent daily bar data is ever sourced, Alt45 is worth re-running on those two symbols only.

## Updated Ranking

1. Momentum rotation top-2 weekly: paper candidate.
2. RSI-2 QQQ mean reversion: shadow/paper-forward candidate.
3. KAMA QQQ trend: shadow/paper-forward candidate.
4. Trustdan Alt45: rejected — data vendor gap.
5. Trustdan Alt10: rejected — data vendor gap.
6. Alorse MACD+BB+RSI: rejected, thin sample.
7. Alorse RSI+EMA: rejected, drawdown/short-side.
8. The Strat 2-1-2: rejected, PBO 0.54, thin signal count.

## Next Action

Do not test further trustdan alternatives until exact TradingView-equivalent daily bar data is sourced. The pattern is consistent across Alt10 and Alt45: the edge does not transfer to yfinance daily bars.
