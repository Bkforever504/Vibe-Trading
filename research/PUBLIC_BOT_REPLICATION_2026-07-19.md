# Public Bot Replication Review - 2026-07-19

## Verdict

No public project inspected provides a verified, transferable "top bot" that should be copied into execution. The mature repositories are engines and research frameworks, not proof of a profitable policy.

The useful path is mechanism replication under our own frozen tests. On the same adjusted liquid-ETF dataset, with one full daily bar of signal delay and 6 bps per unit of turnover, the existing frozen dual-momentum strategy remained the leader.

## Frozen Results

Development ends 2024-12-31. The 2025 through 2026-07-17 extension is consumed evidence after this run.

| Mechanism | Development return | 2025+ return | Double-cost 2025+ | 2025+ max drawdown | 2025+ Sharpe | Block-bootstrap lower 95% |
|---|---:|---:|---:|---:|---:|---:|
| Frozen 252-day top-two ETF momentum | 129.1% | 45.2% | 43.5% | 13.2% | 1.43 | 4.9% |
| SPY buy and hold benchmark | 245.6% | 29.0% | 29.0% | 18.8% | 1.03 | -9.6% |
| QuantConnect EMA 20/60 mechanism | 145.3% | 17.6% | 17.3% | 9.0% | 1.03 | -6.5% |
| SPY 200-day SMA long/cash | 130.9% | 15.3% | 14.9% | 12.0% | 0.87 | -15.0% |
| Diversified Turtle 55/10 mechanism | 72.1% | 8.7% | 5.5% | 12.2% | 0.45 | -16.7% |

Only dual momentum had a positive 95% moving-block bootstrap lower bound in the 2025+ extension. It remains an underlying-ETF result, not an options result or a live promotion.

## What Was Actually Copied

- QuantConnect LEAN's Apache-2.0 `FuturesMomentumAlgorithm` publishes a 20/60 EMA cross with a 0.1% tolerance. The lab reproduced that signal on SPY underlying, not futures.
- The Turtle row reproduces the public 55-day breakout and 10-day exit mechanism, but uses equal active-ETF weights. It does not claim to reproduce ATR sizing, pyramiding, futures rolls, or exact fills.
- Freqtrade was not treated as an alpha source because its official documentation says generated examples are not profitable out of the box and warns about lookahead and recursive bias.
- Hummingbot's market-making code is not portable to SPY options without full order-book, maker-fill, fee-tier, adverse-selection, and inventory data.
- FinRL is a framework. Choosing an RL agent after inspecting the holdout would create another optimization layer and contaminate the evidence.

## Existing Intraday And Volume Retest

- All 16 discovered strategy-shadow programs now have an explicit volume-evidence classification.
- Seven have completed historical volume matrices.
- Five QQQ RSI2 prior-high variants passed the current post-selection bootstrap/year screen.
- Zero volume candidates are high-confidence or forward-promotion ready.
- SPY 15-minute ORB plus CMF direction failed because the holdout bootstrap lower bound remained negative.

The five RSI2 rows are research candidates, not five independent discoveries. They overlap heavily and were selected from one matrix, so they require one frozen candidate and untouched option-aware forward evidence.

## Recovery Finding

The post-hardening Flip bot is +$2,332 across 12 trades, but it peaked at +$2,923 and then lost four consecutive trades for -$591. Every scored trade was labeled 9/10. That score has no discrimination and its Brier score is 0.2767, worse than the constant historical base-rate forecast.

The two recent fully instrumented trades both had `stand_aside` consensus and lost a combined $206. This is too few observations to grant broad veto authority, but it supports the already implemented multi-warning primary caution veto as a paper-only preregistered experiment.

## Source Quality

- QuantConnect LEAN: https://github.com/QuantConnect/Lean
- QuantConnect EMA example: https://github.com/QuantConnect/Lean/blob/master/Algorithm.Python/FuturesMomentumAlgorithm.py
- Freqtrade strategy documentation: https://github.com/freqtrade/freqtrade/blob/develop/docs/strategy-customization.md
- Hummingbot: https://github.com/hummingbot/hummingbot
- FinRL: https://github.com/AI4Finance-Foundation/FinRL
- Deflated Sharpe Ratio: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Time-series momentum: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463

Recent social research was low quality and concentrated in Reddit. It reinforced survivorship bias and the need for small paper sizing, but did not identify a reproducible bot with complete results.

## Decision

1. Keep Flip paper-only and preserve current safety caps.
2. Replace probability language around the repeated 9/10 value with `setup_score` until a calibrated model exists.
3. Freeze one QQQ RSI2 volume candidate before collecting further option-aware outcomes.
4. Continue dual momentum as the lead underlying paper candidate.
5. Do not add Freqtrade, Hummingbot, or FinRL execution code to the current Alpaca path.
