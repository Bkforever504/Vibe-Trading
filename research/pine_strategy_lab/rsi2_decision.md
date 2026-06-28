# RSI-2 Mean Reversion Decision

Date: 2026-06-28

Source: `research/pine_sources/handiko-rsi2/RSI-2 Strategy.pine`

Status: **shadow/paper candidate**, not live execution.

## Best Exact-Source Candidate

The exact Handiko-style exit is `exit_mode=prior_high`, which closes when current close is above the previous bar's high.

| Field | Value |
|---|---:|
| Symbol | QQQ |
| Window | 2018-01-01:2024-12-31 |
| Params | `exit_mode=prior_high, exit_sma=5, rsi_threshold=15, trend_window=200` |
| Confidence | 8.7 |
| PF | 1.59 |
| OOS PF | 1.35 |
| Walk-forward | 0.80 |
| Sharpe | 0.56 |
| Win rate | 76.9% |
| Trades | 91 |
| Max DD | 12.8% |
| Sweep PBO | 0.45 |

## Strongest Variant

The SMA-exit variant performs slightly better, but it is a derived variant rather than the exact source logic:

`QQQ, 2018-2024, exit_mode=sma, exit_sma=5, rsi_threshold=10, trend_window=200`

Confidence 9.1, PF 1.80, OOS PF 1.45, WF 0.80, win rate 76.4%, trades 89, max DD 12.8%.

## Decision

Promote RSI-2 into **shadow-forward testing only**.

Recommended forward-test priority:

1. Track exact-source `prior_high` candidate on QQQ.
2. Track best-performing `sma` variant on QQQ as a comparison arm.
3. Do not wire orders until 30-60 days of forward signals are logged and reviewed.

This strategy is meaningfully different from momentum rotation: it is a short-term pullback system inside a long-term uptrend, while momentum rotation is weekly cross-asset relative strength.
