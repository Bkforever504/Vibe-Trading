# Contextual Breakout and Multi-Timeframe FVG Mechanics — Research Note

**Purpose.** Translate the mechanics in the September 1 screenshots into falsifiable *shadow-research hypotheses*. This is not evidence that any pictured trade was available, entered at the pictured price, or profitable after costs. It is not investment advice.

## What can be stated mechanically

### 1. Inside-bar breakout is a detectable compression event, not a directional edge by itself

For a completed bar `t`, define an inside bar only when:

`high[t] <= high[t-1]` **and** `low[t] >= low[t-1]`.

The preceding bar is the mother bar. A long trigger can be defined ex ante as an executable trade through `high[t] + buffer`; a short trigger as a trade through `low[t] - buffer`. The screenshots' useful claim is not the pattern alone but the proposed **context**: a prior directional move plus a verified earnings/news event or an objectively defined opening gap. That is a testable interaction; it is not proof of an edge.

One recent large-universe public backtest is a useful warning, not an authority: its plain inside-bar rule reported a very small mean result before several real-world costs. Treat it as evidence against promoting the bare pattern, not as validation of its parameter choices. [Tenachine inside-bar study](https://tenachine.com/learn/studies/inside-bar-breakout)

There is stronger methodological precedent for this approach than for any particular screenshot setup. Lo, Mamaysky and Wang formalized chart-pattern identification and tested conditional return distributions rather than relying on visual examples; Brock, Lakonishok and LeBaron tested pre-specified moving-average and trading-range rules against bootstrap null models. Those papers do **not** validate an inside-bar system, but they support formal predicates and a benchmarked statistical test. [Lo, Mamaysky & Wang (MIT-hosted paper)](https://www.mit.edu/~wangj/pap/LoMamayskyWang00.pdf) · [Brock, Lakonishok & LeBaron (1992)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x)

### 2. A multi-timeframe “FVG” must be converted from drawing language to a price interval

For a three-bar sequence `(t-1, t, t+1)`, define a bullish gap interval only after bar `t+1` closes when `high[t-1] < low[t+1]`; its zone is `[high[t-1], low[t+1]]`. Define a bearish interval when `low[t-1] > high[t+1]`; its zone is `[high[t+1], low[t-1]]`. The 4H zone in the screenshot must use completed 4H bars; the 15-minute reaction/entry logic must use bars timestamped after that zone existed. Otherwise the backtest leaks future information.

The claim “price reacts to FVGs” is not enough to justify trading. A 2026 SSRN working paper tested roughly 40,000 FVG observations across liquid futures, found a descriptive reaction above comparable random levels, but reported no tradeable edge after honest construction/costs; one profitable-looking hourly version disappeared on 1-minute exit resolution. It is an unpublished working paper, so it should be reproduced rather than treated as settled fact. [Barot, *Fair Value Gaps Work — Until You Try to Trade Them*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7148099)

## Testable candidate specifications

These are proposed experiments, not live rules. Each requires a preregistered version, held-out period, and realistic bid/ask/slippage assumptions.

| Hypothesis | Fully specified observation | Entry / failure / outcome | Required controls |
|---|---|---|---|
| Contextual inside-bar continuation | A completed inside bar on timeframe `T`; before its close, a verified issuer filing/earnings release **or** objective gap threshold `G`; pre-specified directional trend feature `M` | Enter only after an executable break of the inside-bar boundary; initial stop at opposite boundary plus spread buffer; fixed `R` targets and time stop | Compare with the same inside-bar rule without catalyst/gap and with randomly selected same-volatility bars; use only information available at decision time |
| 4H FVG → 15m reaction | Completed 4H gap interval; price later enters that interval; define 15m “aggressive reaction” quantitatively (e.g., a close outside the zone by `x × ATR_15`) | Do **not** enter merely on touch. Require a subsequent completed 15m three-bar gap in the reaction direction; entry at its predeclared boundary/retest; stop beyond reaction swing; target 2R/3R | Separate instruments, sessions, long/short, and first-touch vs later-touch; compare with equally sized synthetic zones at the same distance |
| Catalyst + compression | Verify catalyst from issuer IR/SEC filing before the signal, then measure whether a post-event inside bar has different conditional outcomes from a matched non-event inside bar | Same as first row | Event timestamp must precede setup; record filing URL, publication time, symbol, and catalyst type. Exclude social posts as the source of truth |

`M`, `G`, `x`, time windows, entry buffer, fee/slippage model, maximum concurrent positions, and target/stop handling must be frozen before looking at results. Parameter searches belong in discovery; they are not validation.

If multiple variants are searched, report the number searched and protect the final claim with a locked chronological holdout/walk-forward test. White's Reality Check was designed to address data-snooping among selected rules, while Bailey et al. formalize the risk that an in-sample winner fails out of sample. [White (2000)](https://onlinelibrary.wiley.com/doi/10.1111/1468-0262.00152) · [Bailey et al., *Probability of Backtest Overfitting*](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)

## What is hindsight versus admissible evidence

The social posts illustrate ideas, but screenshots of option P/L are not a research record: they normally omit timestamped alert delivery, full trade list, fills, position size consistency, commissions/spread, losing trades, and whether an exit could have been executed. The SEC specifically advises investors not to make decisions solely from unverified social-media information and has brought cases involving misleading online stock recommendations. [SEC: Citron Capital enforcement release](https://www.sec.gov/newsroom/press-releases/2024-89) · [SEC: Social-media stock-tip alert](https://www.sec.gov/files/litigation/litreleases/2024/26187-investor-alert-investor.pdf)

For the scanner, an alert is eligible for review only when it stores:

1. **Immutable decision-time data:** bar close timestamps, NBBO/quote (where available), indicator values, source URLs, and scan run ID.
2. **A defined trigger, invalidation, target and expiry:** no later redraw of a level and no “entered somewhere in this area.”
3. **A thesis label:** `technical`, `event-driven`, or `options-flow/level`. Event-driven claims require a primary source; a social post may be a lead only.
4. **A counterfactual and cost model:** comparable non-signal cases plus bid/ask, commissions, slippage, and delayed-alert sensitivity.
5. **Out-of-sample promotion criteria:** enough independent trades, expectancy after costs, drawdown, adverse excursion, and stability across time/instruments. Do not promote from a single day, a cherry-picked chart, or optimized in-sample results.

For the SPXW screenshots, an index-direction result is not automatically an option result. Cboe specifies a $100 multiplier and European exercise/cash settlement for SPX options, while the OCC/OIC notes that short-dated options can lose their entire debit and have rapidly changing time value. Any option-version evaluation therefore needs timestamped option bid/ask, IV/greeks, spread/slippage, and forced-exit assumptions—not underlying direction alone. [Cboe SPX specifications](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications/) · [OIC 0DTE primer](https://www.optionseducation.org/news/0dte-options-primer-what-investors-should-know-about-expiration-day-positions)

## Practical A+/B+ implication

An A+/B+ label should be an *audit status*, not an order instruction. “A+ manual-review eligible” should require: completed setup, predeclared entry/stop/target, freshness/no-chase check, a valid thesis source appropriate to its type, sufficient liquidity/quote quality, and portfolio-risk approval. A B+ can remain a watch or a smaller, separately tested cohort; it must never bypass hard risk gates. Neither label establishes a positive expected value until the preregistered shadow results do.

## Source quality note

The formal bar/interval definitions and experiment design above are deterministic conventions so the system can test them. The FVG paper is directly relevant empirical research but is an SSRN working paper, not a regulatory or exchange rule. SEC material is authoritative on the danger of relying solely on social-media claims, not on the profitability of price patterns. No authoritative source found establishes the screenshots' CRT/GEX/FVG combinations as a generally profitable strategy; that absence is precisely why the system should treat them as unvalidated hypotheses.
