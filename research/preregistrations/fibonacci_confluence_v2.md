# Fibonacci Confluence v2 Preregistration

Created after v1 failed and before v2 outcomes were computed. The v1 holdout is
therefore no longer pristine. V2 results are exploratory until forward data or
external-instrument checks confirm them.

## Corrections From v1

- Anchor the latest meaningful completed impulse using a causal ATR-ZigZag.
- Confirm each swing endpoint only after a 0.75 ATR reversal.
- Require the impulse to span at least 2.0 ATR.
- Test canonical 0.382, 0.500, and 0.618034 levels.
- Stop beyond the 100% swing origin plus 0.05 ATR, not at 0.786.
- Fill at the next bar open; use stop-first same-bar ambiguity.

## Staged Stack

1. `fib_touch`: level touch only.
2. `fib_rejection`: directional rejection candle after touch.
3. `fib_rejection_trend`: EMA(20)/EMA(50) alignment and EMA(20) slope.
4. `fib_rejection_trend_vwap`: close on the directional side of session VWAP.
5. `fib_rejection_trend_vwap_volume`: rejection-bar volume at least 1.20 times
   its trailing 20-bar median.

No stage may change an earlier stage's anchors, stops, targets, costs, or fill
timing. SPY is the selection instrument. QQQ and IWM are external checks.

## Costs And Review

- Base round-trip cost: 2 bps of entry price.
- Stress cost: 4 bps.
- Development: 2020-2023; selection: 2024; final: 2025 onward.
- A stage is evidence-positive only with at least 40 final SPY trades, positive
  final expectancy, final profit factor at least 1.10, positive doubled-cost
  expectancy, and positive expectancy on both QQQ and IWM external checks.
- Passing authorizes paper-only shadow comparison, never live execution or size.
