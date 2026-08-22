# Commercial TradingView Indicator Proxy Results

Date: 2026-07-25

## Verdict

No tested commercial-indicator methodology proxy passed the frozen promotion
gates on SPY and MES. No indicator family was added to an execution bot or
scheduled as a shadow strategy.

The least-bad family was `squeeze_release`. Its 2025+ expectancy was positive
on both markets, but it failed the 2024 selection period, failed double-cost
stress, had weak profit factors, and had confidence intervals spanning zero.
That is not enough evidence to trade it.

## What Was Actually Tested

Invite-only and protected Pine source cannot be inspected legally or
technically. The lab therefore used independent implementations of mechanics
the vendors describe publicly:

| Proxy | Public methodology represented |
|---|---|
| Adaptive trend pullback | KAMA, ATR trend trail, EMA reclaim, relative volume |
| Oscillator money flow | WaveTrend, MFI, VWAP, EMA trend |
| Liquidity structure reclaim | Prior-range sweep, reclaim, displacement, volume |
| Multi-oscillator consensus | RSI, MACD, stochastic, ADX, EMA trend |
| Velocity EMA ribbon | 13/48/200 EMA alignment, ATR expansion, pullback |
| Squeeze release | Bollinger/Keltner compression release, volume, EMA trend |

These correspond to public concepts marketed by LuxAlgo, Market Cipher,
AlgoAlpha, ChartPrime, Zeiierman, and similar paid suites. They are not copies
of proprietary vendor code and do not evaluate vendor-specific hidden logic.

TradingView itself distinguishes open-source, protected, and invite-only
scripts:

- https://www.tradingview.com/support/solutions/43000558522-what-are-community-scripts/
- https://www.tradingview.com/pine-script-docs/writing/publishing/

Vendor methodology references:

- LuxAlgo signals and overlays:
  https://docs.luxalgo.com/docs/algos/signals-overlays/signals
- Market Cipher money flow:
  https://marketciphertrading.com/what-is-money-flow-and-why-does-it-matter/
- AlgoAlpha indicator suites:
  https://docs.algoalpha.io/docs/indicators
- ChartPrime documentation:
  https://docs.chartprime.com/
- Zeiierman documentation:
  https://docs.zeiierman.com/

Vendor claims were treated as hypothesis descriptions, not profitability
evidence.

## Frozen Test

- Real SPY and MES one-minute data, aggregated to five-minute real-price bars.
- One trade per family per complete session.
- Signal window 10:00 through 13:30 ET.
- Entry on the next bar open.
- Stop 1.25 ATR, target 1.75R, stop first on same-bar ambiguity.
- SPY cost: one basis point per side.
- MES cost: one tick per side plus $2.48 round trip.
- Development 2022-2023, selection 2024, consumed diagnostic 2025+.
- No parameter sweep.

SPY results are underlying-price tests. They do not model option IV, Greeks,
historical NBBO, or spread fills.

## Results

Expectancy is net R per trade.

| Market | Family | Trades | Dev exp | 2024 exp | 2025+ trades | 2025+ exp |
|---|---|---:|---:|---:|---:|---:|
| MES | Adaptive trend | 496 | -0.1670 | -0.2555 | 174 | -0.0997 |
| MES | Oscillator money flow | 23 | 0.0108 | 0.3978 | 5 | -0.4429 |
| MES | Liquidity reclaim | 72 | -0.1522 | 0.1617 | 25 | -0.6490 |
| MES | Multi-oscillator | 888 | -0.0024 | -0.0698 | 291 | -0.0632 |
| MES | Velocity ribbon | 567 | -0.2886 | -0.3446 | 198 | -0.0948 |
| MES | Squeeze release | 308 | 0.1187 | -0.1929 | 108 | 0.0687 |
| SPY | Adaptive trend | 134 | -0.1281 | -0.6450 | 74 | -0.3073 |
| SPY | Oscillator money flow | 7 | -0.3221 | n/a | 5 | -0.0994 |
| SPY | Liquidity reclaim | 48 | -0.1770 | 0.5840 | 13 | -0.0869 |
| SPY | Multi-oscillator | 288 | 0.1382 | 0.0901 | 149 | -0.0357 |
| SPY | Velocity ribbon | 186 | -0.2399 | -0.3752 | 102 | -0.1505 |
| SPY | Squeeze release | 107 | 0.0331 | -0.1142 | 52 | 0.0573 |

Squeeze release 2025+ stress:

| Market | PF | Double-cost exp | Top 1% removed | 95% block interval |
|---|---:|---:|---:|---|
| MES | 1.1115 | -0.0537R | 0.0378R | [-0.1513, 0.2612] |
| SPY | 1.0918 | -0.1223R | 0.0254R | [-0.3233, 0.4302] |

All 12 market-family promotion decisions failed.

## Alpaca Loss Repair Shipped

The audit found that the options journal stored submitted limit credits instead
of broker fills. Current paper groups were backfilled from Alpaca GET order
snapshots:

| Group | Stored quote | Actual fill | Old max risk | Corrected max risk |
|---|---:|---:|---:|---:|
| IWM iron condor | $0.62 | $0.40 | $138 | $160 |
| AAPL put spread | $1.04 | $0.86 | $396 | $414 |
| NVDA put spread | $0.57 | $0.49 | $243 | $251 |

New behavior:

- Accepted but unfilled MLEG orders are `pending`, not `open`.
- A verified Alpaca fill becomes the credit and risk basis.
- Pending entries block duplicate exposure until resolved.
- A `stand_aside` recommendation with at least two warnings blocks a new
  options entry and writes a decision-log event.
- The shared Flip consensus behavior and all option exit paths are unchanged.
- Alpaca remains paper-only.

Backup:

`C:\Users\kenne\.vibe-trading\backups\options-trades-pre-fill-truth-20260725-211609.json`

## Confidence

- Fill/accounting repair: 9/10. Broker snapshots, idempotent migration, and
  focused plus downstream tests support it.
- Multi-warning options caution gate: 5/10. It is sensible damage control, but
  only blocked-versus-taken forward evidence can validate it.
- Paid-indicator alpha: 2/10. No family passed.
- Current bot profitability: below promotion confidence. Paper-only remains
  mandatory.

## Verification

- Commercial proxy, prior indicator, and options focused tests: 42 passed.
- Options state, lifecycle, reporting, and confidence integration: 68 passed.
- No paid indicator was purchased.
- No order was placed by this research.
- No current strategy was promoted.

Artifacts:

- `research/COMMERCIAL_INDICATOR_PROXY_PREREGISTRATION_2026-07-25.md`
- `research/commercial_indicator_proxy_lab.py`
- `data/commercial_indicator_proxy_results.json`
- `agent/tests/test_commercial_indicator_proxy_lab.py`
- `research/INDICATOR_RECIPE_RESULTS_2026-07-25.md`
