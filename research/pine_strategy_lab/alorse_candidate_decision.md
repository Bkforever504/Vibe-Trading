# Alorse Strategy Candidate Decision

Date: 2026-06-28

Research only. No live execution wiring was added.

## RSI + EMA

Source:
`research/pine_sources/alorse-pinescript-strategies/strategies/momentum/RSI + EMA.pine`

Python port:
`research/pine_strategy_lab/examples/alorse_rsi_ema_python.py`

Decision: rejected.

Best row:

- Symbol/window: XLE, 2015-01-01 to 2024-12-31
- Params: RSI 10, overbought 70, oversold 30, EMA 150/600
- Confidence: 5.6
- PF: 1.96
- OOS PF: 1.76
- WF: 0.80
- Trades: 19
- Max DD: 64.6%
- PBO: 0.50

Why rejected:

- The strategy shorts overbought RSI while the EMA regime is bullish.
- That short-side design produced unacceptable drawdown on equity/sector ETFs.
- Rows with acceptable drawdown had weak OOS, low Sharpe, or too few trades.

Verdict:
Do not tune into production. If revisited, test a separately named long-only derivative so it is not confused with the source strategy.

## MACD + BB + RSI

Source:
`research/pine_sources/alorse-pinescript-strategies/strategies/momentum/MACD + BB + RSI.pine`

Python port:
`research/pine_strategy_lab/examples/alorse_macd_bb_rsi_python.py`

Decision: rejected for now.

Best row:

- Symbol/window: SPY, 2015-01-01 to 2024-12-31
- Params: fast 8, slow 21, signal 5, BB 20/2.0, RSI 10, entry RSI < 55, exit RSI > 70, green-bar filter on
- Confidence: 6.3
- PF: 5.54
- OOS PF: 99.00
- WF: 0.60
- Trades: 12
- Max DD: 21.2%
- PBO: 0.20

Why rejected:

- Trade count is far below the 30-trade minimum.
- OOS PF of 99.00 is a thin-sample artifact, not evidence of a stable edge.
- Walk-forward stability is only borderline despite the low PBO score.

Verdict:
Do not promote. It can remain in the research backlog, but RSI-2 and momentum rotation are stronger current candidates.

## Current Ranking After Tests

1. Momentum rotation top-2 weekly: paper candidate.
2. RSI-2 QQQ mean reversion: shadow/paper-forward candidate.
3. Alorse MACD + BB + RSI: rejected, low sample.
4. Alorse RSI + EMA: rejected, drawdown/short-side issue.

Next candidates:

- GeekTrade ETH breakout, only after auditing `request.security` and crypto-specific assumptions.
- Alorse TTM Squeeze only after fixing its default no-stop/no-real-exit behavior as a derived strategy.
