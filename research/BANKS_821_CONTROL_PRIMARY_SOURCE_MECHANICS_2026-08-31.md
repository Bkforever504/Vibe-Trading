# Banks 8/21 Control — Primary-Source Mechanics Intake

Reviewed: 2026-08-31  
Scope: the public mechanics attributed to Justin Banks / `@RealJGBanks`; not marketing-return claims or evidence of profitability.

## Source and evidence standard

The principal source is Banks's self-published, eleven-page **The BANKS Top-Down Trading Blueprint**, attributed to `@RealJGBanks` and hosted at [Google Drive](https://drive.google.com/file/d/1hExAtfctbRRswfun4kbvcyFchWtl18iY/view). It is first-party evidence of the process he states, not independent evidence that the process has positive expectancy. The supplied Banks Bot post independently corroborates only the five marketed headings: “8/21 Control,” “Major Key Levels,” “Trend,” “Break + Retest,” and “Momentum.”

The playbook itself describes its examples as historical, says they do not guarantee future results, and says the trader—not the product—chooses entry, invalidation, sizing, and fit.

## What is actually specified

| Component | Directly evidenced rule | Implementation-safe interpretation |
|---|---|---|
| Top-down sequence | Weekly/Daily finds bias; Daily/1H maps structure; 1H/setup timeframe waits for the event; 5m/15m waits for the retest and executes. | Build higher-timeframe context before permitting an entry-timeframe candidate. Do not use 5m alone to invent a setup. |
| Major key levels | Mark major support/resistance, prior highs/lows, supply/demand, and obvious decision areas. | Candidate level families may include those named categories, but the source supplies no ranking, zone width, or selection algorithm. |
| Break / reclaim / loss | A break, reclaim, or loss “must be accepted beyond structure”; a wick is insufficient. The checklist asks whether it confirmed on a **closed candle**. | Require a completed-bar close beyond the level for acceptance; require a completed-bar close back through the level for reclaim/loss logic. |
| Retest | After acceptance, price returns to the level or “8/21 area”; it must hold/reject rather than force a chase. | Treat a fresh retest of the accepted level or EMA area as required confirmation; reject a raw breakout entry. The exact touch/hold tolerance is unspecified. |
| 8/21 control | The 8 EMA is the fast trend guide; the 21 EMA is deeper defense. The 8/21 cross identifies a control shift, but is “context—not a button” and not automatic permission to trade. | Use EMA(8)/EMA(21) alignment or cross as a context filter only, jointly with structure, acceptance, and retest. Do **not** permit an EMA-cross-only entry. |
| Trend | In the bullish example, the 8 crossed above the 21 and price held the new side; in the bearish example, the 8/21 crossed down and price remained below the averages. | A candidate directional state can require both EMA relation/cross direction and price acceptance on that side; exact lookback/persistence is not specified. |
| Momentum | Post-retest, the hold/rejection should be followed by momentum “re-expanding” in the trade direction; weak/sideways follow-through is a no-trade condition. | Require a separate, preregistered post-retest expansion test. The source does not define it as volume, range, ROC, relative strength, or another indicator. |
| No-trade conditions | Do nothing for ranging/compressing or repeatedly crossing 8/21, no fresh location, weak/sideways momentum, repeated level chop, extended distance from 8/structure, conflicted evidence, or a late entry. | These are admissible blocker hypotheses. Each needs an independent measurable definition before it can block or score a live candidate. |

## Smallest source-faithful, testable sequence

This is a **translation for independent shadow testing**, not a claim that Banks publishes these exact thresholds:

1. Establish a directional context using Weekly/Daily and map a major level on Daily/1H.
2. On the setup timeframe, require a completed candle to accept beyond, reclaim, or lose that level; a wick alone fails.
3. Require 8/21 context to agree with the direction. A cross alone fails.
4. On 5m/15m, wait for the first return to the accepted level or 8/21 area.
5. Require a completed hold/rejection and a separately defined directional momentum re-expansion.
6. Reject the candidate when it is extended, late, choppy, weak, or internally conflicted; define invalidation before entry.

## Parameters the public source does **not** define

Do not call any of the following “Banks rules” unless later first-party material specifies them:

- EMA calculation price, session treatment, timeframe for the general 8/21 filter, and exact cross/persistence logic. (One example is explicitly daily; the framework spans several timeframes.)
- Which listed levels take precedence, how zones are drawn, and breakout/retest tolerance.
- The exact definition or measurement of “hold,” “reject,” “accepted,” “momentum re-expanding,” “extended,” “repeated chop,” and “conflicted.”
- Stop placement, target/exit method, holding period, position sizing, universe, liquidity/news filters, and transaction-cost assumptions.
- Any complete trade ledger, sampling protocol, out-of-sample validation, or performance statistic.

## Integration boundary

Implement this as an isolated **8/21 context + structure acceptance + first-retest** shadow family. Freeze every missing parameter in a preregistration, test it against an appropriate non-EMA structure/retest baseline, and retain per-candidate no-trade/blocker reasons. It should not alter execution authority or any existing frozen strategy until forward, cost-aware evidence supports it.

## Source details

- [The BANKS Top-Down Trading Blueprint (author-hosted Google Drive PDF)](https://drive.google.com/file/d/1hExAtfctbRRswfun4kbvcyFchWtl18iY/view), pp. 1–4: top-down sequence, closed-candle acceptance, retest logic, and 8/21 context.
- [Same source](https://drive.google.com/file/d/1hExAtfctbRRswfun4kbvcyFchWtl18iY/view), pp. 5–9: examples showing daily bullish control, retested zone, bullish/bearish 8/21 alignment, failed reclaim, and broken-support retest.
- [Same source](https://drive.google.com/file/d/1hExAtfctbRRswfun4kbvcyFchWtl18iY/view), pp. 10–11: no-trade list, pre-entry checklist, risk/discretion disclaimer, and non-guarantee disclosure.
