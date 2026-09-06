# BananaPatterns mechanics intake — 2026-08-31

## Verdict

**Not eligible for the shadow tournament yet.** BananaPatterns publishes a useful, testable *screening framework* for end-of-day Indian-equity base breakouts, but it does not publish a fully reproducible executable strategy. The missing information is material: a generalized VCP definition, volume threshold, pivot construction rule, break-even trigger, trailing-stop rule, exit timing/priority, and cost/execution assumptions. Its own backtest is labelled provisional and under methodology review.

This is a research intake, not a recommendation and not a performance endorsement.

## What is actually documented

| Component | First-party rule | Status |
| --- | --- | --- |
| Universe / cadence | Roughly 4,500 Indian listed equities, read nightly after the NSE/BSE close; screen floor is approximately INR 500 crore market value and INR 5 crore daily turnover. It is explicitly an end-of-day, daily-chart process. | Usable as a universe/cadence specification. |
| Core pattern | A strong prior uptrend, a base with successively shallower pullbacks, fading volume, a defined pivot/ceiling, then a price clearance with volume confirmation. The illustrative contractions are roughly -25%, -15%, and -8%; the page says a usual VCP has two to four contractions. | Qualitative only; illustrative values are not a generalized preset. |
| Entry | A breakout is a close above the base pivot. The backtest interface describes two modes: buy at breakout-day close, or assume a fill at the pivot. | Candidate entry modes are stated; no market-order/slippage implementation. |
| Initial risk | The site says risk is about 1.5% of capital per trade and sets an auto-sell about 8% below entry; a guide describes the usual stop as 7-8%. | Approximate—not one fixed rule. |
| Winner exit | Lock in no loss once sufficiently profitable; raise a trailing stop; step off when trend breaks. Some records describe exits as below the 50-day line. | Incomplete: activation threshold, trailing formula, and priority are absent. |

## Published screen presets

These are eligibility screens, not verified complete trade systems.

| Screen | Published requirements |
| --- | --- |
| Blue Sky | Base at all-time high; relative strength 70-99; within 20% of pivot. |
| Multi-year | Base at least 52 weeks; price above 200-day MA; relative strength 60-99; within 20% of pivot. |
| IPO Base | Listing age 2-50 weeks; base at least 3 weeks and 2-35% deep; above 50-day MA; within 20% of pivot; no RS filter. |
| VCP | Strong prior trend, tightening contractions, declining volume, clear pivot, breakout with volume. A case study had a 13-week, 22%-deep base, but that is an example—not a universal parameter set. |

## Data and evidence limits

- BananaPatterns says its data are rebuilt from official exchange data after each close, but its terms say it relies on third-party market data that may contain errors, delays, or omissions.
- Its own disclaimer says historical results are hypothetical and flags survivorship bias, investable-universe changes, and hindsight.
- I found no published assumptions for brokerage, taxes, spreads, slippage, corporate actions, delistings, execution gaps, or adjusted-price handling.
- The indexed backtest states that results are **provisional** and under methodology review. Its descriptive claim of roughly one winner in three is not accepted as evidence of forward performance.

## What would make it tournament-eligible

Request or locate the missing versioned specification:

1. Exact VCP/base detection algorithm and pivot construction.
2. Exact volume baseline and minimum breakout-volume multiple.
3. One fixed entry convention (with time, order type, and gap rule).
4. Fixed stop, break-even, and trailing/50-day exit sequencing.
5. Historical, point-in-time universe and fully specified transaction-cost model.
6. A locked in-sample/out-of-sample split and forward-shadow protocol.

If that source material becomes available, implement it first as a separate **EOD Indian-equity shadow challenger**. It should not be merged into the current U.S. intraday A+ scanner: the holding period, market, data cadence, and mechanics are different.

## Sources (first party)

- [BananaPatterns home / method and disclaimer](https://bananapatterns.com/)
- [VCP guide](https://bananapatterns.com/learn/volatility-contraction-pattern)
- [How to use BananaPatterns / universe and cadence](https://bananapatterns.com/learn/how-to-use-bananapatterns)
- [Blue Sky breakout rules](https://bananapatterns.com/learn/blue-sky-breakout-pattern)
- [Multi-year breakout rules](https://bananapatterns.com/learn/multi-year-breakout-pattern)
- [IPO base rules](https://bananapatterns.com/learn/ipo-base-pattern)
- [VCP case study: Rashi Peripherals](https://bananapatterns.com/notes/rashi-peripherals-vcp-breakout)
- [Backtest interface text / illustrative exit ledger](https://bananapatterns.com/stock/somany-ceramics)

