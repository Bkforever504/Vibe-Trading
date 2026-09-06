# Mechanical strategy intake — 2026-08-31

Status: **research candidates only.** None of these rules alter scanner ranks, alerts, sizing, or execution. A source-code rule is testable; it is not evidence that the rule is profitable after costs or outside its source market.

## Acceptance standard

A candidate is complete enough to test only if all of these are explicit: market and bar interval, indicator/level construction, completed-bar entry, initial invalidation, exit, and position/re-entry constraints. It still needs a preregistered train/out-of-sample tournament plus forward shadow observation before any consideration for the scanner.

## Candidate M-01 — Supertrend/Fisher reversal short

**Source market and interval:** Binance BTC/USDT futures, two-minute decision bars built from one-minute base data in the source backtest configuration ([source code](https://github.com/fmzquant/strategies/blob/master/%E5%B8%82%E5%9C%BA%E9%80%86%E8%BD%AC%E5%8F%8C%E9%87%8D%E5%8A%A8%E9%87%8F%E7%AD%96%E7%95%A5Market-Reversal-Momentum-Strategy.md)). This is not an equity/options claim.

**Fully specified mechanics:**

1. Compute Fisher Transform from `hl2` with length 10 using the recurrence in the source.
2. Compute Supertrend from `hl2`, ATR(10), multiplier 2, with the source's trailing-band recurrence.
3. On a completed bar, enter short only when the Supertrend state flips from `+1` to `-1` **and** Fisher is above 2.5 and declining versus the preceding Fisher value.
4. Enter at that completed-bar close in the source's Pine convention. Initial stop is entry + `2 × ATR(10)`.
5. Take profit is entry − `2 × ATR(10)`; close if a completed bar reaches either threshold. The source submits one unit and does not define a re-entry cooldown, so the tournament must explicitly prohibit overlapping positions and define a next-bar fill convention.

**Why it is new/useful:** it is a clean, complete *reversal* challenger with a different hypothesis from our existing level-reaction and trend-continuation lanes. Its rules can be reproduced exactly without guessing what a social-media creator meant.

**Why it is not ready for our scanner:** it was authored for crypto futures, uses a very short sample window, and is short-only. Porting it to liquid equities, ETFs, or index futures would be a new hypothesis. The source's own code is the authority for the mechanics; its performance discussion is not accepted as proof. A portable tournament needs fixed parameters, instrument-specific costs/slippage, year-blocked OOS periods, and an explicit no-overlap rule.

## Rejected source: "advanced" FVG rule

The same repository exposes a second fully coded FVG strategy, but its prose says 15-minute bars while its declared backtest configuration says daily BTC/USDT bars; its stop is an account-equity loss threshold rather than an instrument-price invalidation ([source code](https://github.com/fmzquant/strategies/blob/master/Advanced-Fair-Value-Gap-Detection-Strategy-with-Dynamic-Risk-Management-and-Fixed-Take-Profit-%E5%9F%BA%E4%BA%8E%E5%8A%A8%E6%80%81%E9%A3%8E%E9%99%A9%E7%AE%A1%E7%90%86%E5%92%8C%E5%9B%BA%E5%AE%9A%E8%8E%B7%E5%88%A9%E7%9A%84%E9%AB%98%E7%BA%A7%E5%85%AC%E5%85%81%E4%BB%B7%E5%80%BC%E7%BC%BA%E5%8F%A3%E6%A3%80%E6%B5%8B%E7%AD%96%E7%95%A5.md)). That contradiction makes it unsuitable for intake until an unambiguous specification is available.

## Next research gate

Before adding M-01 to a tournament, preserve the source parameters and preregister:

1. A small fixed universe (for example, ES, NQ, SPY, QQQ), one data vendor, one bar convention, and a complete date range.
2. Signal at bar close; entry no earlier than next bar/open or a documented conservative fill rule.
3. One position per instrument, no same-bar stop/target optimism, explicit commissions and adverse slippage.
4. Calendar-blocked in-sample/OOS splits, stability across instruments, and forward-shadow reporting.
5. A promotion threshold that requires stable OOS expectancy and drawdown, not win rate or a social-media return screenshot.
