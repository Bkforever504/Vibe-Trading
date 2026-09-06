# YouTube process intake — Captain Trading / `meDaCUb1vtQ`

**Status:** research intake only; not a production trading specification.  
**Video:** [J'ai automatisé mon analyse technique : Voici le résultat](https://www.youtube.com/watch?v=meDaCUb1vtQ) (Captain Trading, published 2026-08-29; 11:25).  
**Resolved source:** [`https://t.co/tyBTuItDFY`](https://t.co/tyBTuItDFY) → [`https://www.youtube.com/watch?v=meDaCUb1vtQ`](https://www.youtube.com/watch?v=meDaCUb1vtQ).

## Evidence quality and boundaries

- The author’s YouTube description and chapter markers are the primary evidence below. The watch page exposes only a French *auto-generated* caption track in metadata, while YouTube’s own transcript export reports that no transcript is available and the player reports captions unavailable. Consequently, this intake does **not** invent spoken parameters that cannot be verified from the accessible first-party material.
- The description identifies the workflow as crypto scanning on **OKX**, with **Claude AI**, **TradingView**, the **Choppiness Index**, and **SFP** patterns. It explicitly says that risk is calculated and orders are placed as limits on OKX, but supplies no numeric configuration. [Official video description](https://www.youtube.com/watch?v=meDaCUb1vtQ)
- Promotional or testimonial language (for example, that a system saves time or that an AI-enabled trade would otherwise not have been taken) is excluded as evidence of performance.

## Reconstructed process

| Stage | Explicit process element | Tool / market | Evidence |
|---|---|---|---|
| 1. Connect data and analysis | Connect Claude AI to TradingView, then use the OKX ecosystem as the asset universe. | Claude AI; TradingView; OKX crypto assets | [01:15–02:17](https://www.youtube.com/watch?v=meDaCUb1vtQ&t=75s) |
| 2. Generate initial universe | Have AI create relevant watchlists while scanning a large OKX universe. | Claude AI; OKX | [description and 00:28–01:36](https://www.youtube.com/watch?v=meDaCUb1vtQ&t=28s) |
| 3. Filter for regime / volatility | Apply a filter based on the **Choppiness Index**. | Choppiness Index | [02:18–03:47](https://www.youtube.com/watch?v=meDaCUb1vtQ&t=138s) |
| 4. Inspect shortlisted names | Import the resulting watchlist into TradingView and conduct trade analysis. | TradingView | [03:48–05:15](https://www.youtube.com/watch?v=meDaCUb1vtQ&t=228s) |
| 5. Apply pattern confirmation | The description says the strategy uses **SFP** patterns alongside the Choppiness Index to filter volatility. No SFP definition or rules are accessible. | Price-action pattern labelled “SFP” | [official description](https://www.youtube.com/watch?v=meDaCUb1vtQ) |
| 6. Alternative / additional filter | Filter for rising volume. | Volume | [05:16–06:26](https://www.youtube.com/watch?v=meDaCUb1vtQ&t=316s) |
| 7. Manually select and execute | Manually select a candidate; the illustrated position is SOL. Calculate risk, then place a **limit** order on OKX. | SOL; OKX | [06:27–09:03](https://www.youtube.com/watch?v=meDaCUb1vtQ&t=387s) |
| 8. Refine filters | Continue refining filters / advanced indicators. This is described as an iteration step, not an autonomous execution rule. | AI / indicators | [09:54–11:00](https://www.youtube.com/watch?v=meDaCUb1vtQ&t=594s) |

### Implementable flow (only at the stated level of detail)

`OKX universe → AI-generated watchlist → Choppiness filter → rising-volume filter → TradingView review → SFP / discretionary confirmation → position-size / risk calculation → OKX limit order`

The video’s own description characterizes the watchlist as an aid to filtering and explicitly includes **manual selection** before the SOL position. Treat it as a semi-automated research workflow, not as a fully automated trading system.

## Trading rule extraction

| Field | Extracted rule | Confidence / gap |
|---|---|---|
| Instruments | Crypto assets listed on OKX; SOL is the worked example. | **High** for venue and SOL example; no fixed tradeable-universe definition. |
| Timeframes | Not stated in accessible first-party material. | **Missing.** |
| Long / short direction | Not stated. | **Missing.** |
| Setup / regime condition | Use a Choppiness Index-based volatility filter. | **Medium:** indicator is named, but no lookback, threshold, direction, or pass/fail polarity is given. |
| Volume condition | “Increasing/rising volume” is used as a filter. | **Medium:** no formula, lookback, baseline, or threshold is given. |
| Pattern condition | SFP is part of the described strategy. | **Low-to-medium:** no definition, structure, confirmation candle, or invalidation rule is provided. |
| Entry | Candidate is manually selected after TradingView analysis; execute a **limit** order on OKX. | **High** for manual review + limit order; **missing** trigger price, order validity, and direction. |
| Stop / invalidation | No stop-loss location or pattern invalidation is disclosed. | **Missing.** Risk calculation alone is not an invalidation rule. |
| Position sizing / risk | The presenter says risk is calculated before execution. | **Low-to-medium:** no account-risk %, sizing equation, leverage, margin mode, or maximum exposure is supplied. |
| Exit / take profit | Not disclosed. | **Missing.** |
| Fees / execution | Limit orders on OKX are described as a way to optimize fees. | **Medium:** no order-book, fill, slippage, or fee assumptions are supplied. |

## Minimum clarifications required before any backtest or implementation

1. Exact asset-universe constraints: spot versus perpetuals, liquidity/volume floors, quote currency, exclusions, and scanning cadence.
2. Choppiness Index configuration: timeframe, length, threshold(s), and whether high or low readings qualify.
3. Definition of “rising volume”: bar timeframe, comparison window, threshold, and whether it is relative or absolute.
4. Exact SFP rule: swing definition, wick/body requirement, confirmation, long/short symmetry, and invalidation.
5. Entry trigger and limit-price method; order cancellation/expiry rules; handling of missed fills.
6. Protective stop, profit target(s), trailing or time exit, and what changes when the setup invalidates.
7. Position-sizing equation, per-trade and portfolio risk caps, leverage/margin, correlation limits, and maximum concurrent positions.
8. Test protocol: historical sample, fees, funding, slippage, out-of-sample split, and treatment of delisted/illiquid assets.

## Practical conclusion

This is a **screening and discretionary execution workflow**. It is useful as a research outline—automate the universe/watchlist construction, then validate candidates manually in TradingView—but it is not reproducible as a rule-based strategy from this video alone. In particular, no measurable entry trigger, stop/invalidation, exit rule, risk limit, timeframe, or threshold is accessible from first-party materials.
