# A+ intraday equity setup anatomy: evidence-backed operating standard

**Purpose.** This is a selection and risk-control standard for a shadow-only intraday equity research system. It is not evidence that any indicator, chart pattern, or social-media call is profitable. A candidate earns the internal label **A+** only when it passes every required gate below and when the specific entry/exit rule has separately passed preregistered out-of-sample testing with realistic costs.

## The important distinction

There is no universal, research-proven "perfect trade." Public information can produce price discovery and volatility; liquid quotes and transactions make an execution decision measurable; a completed-bar trigger makes a hypothesis testable. None of those facts proves a positive expected return. The right scientific objective is therefore:

> **A+ = best available evidence, cleanest implementation conditions, and a fully specified risk decision — never a prediction or a guarantee.**

## Required decision chain

| Gate | Required observation / rule | Why it belongs in the process | Status |
|---|---|---|---|
| 1. Public catalyst | A timestamped, attributable public event: SEC filing, issuer news release, scheduled earnings/call, exchange notice, or verified broad news source. Record publish time, source URL, ticker, event type, whether the fact is new versus commentary, and a measurable surprise/context field when available. | Regulation FD requires broad public dissemination for covered material disclosures; original event-study research finds rapid price adjustment around scheduled announcements, while other original research shows that post-news drift varies with the information environment. A filing or issuer release gives a reproducible clock; a retrospective social post does not. | **Evidence-backed process control**; catalyst direction/magnitude is not guaranteed. |
| 2. Market and sector context | At signal time record SPY/QQQ direction, sector ETF direction, index volatility proxy, and whether the ticker move agrees, disagrees, or is idiosyncratic. Compare subsequent results by regime rather than assuming one rule survives every regime. | SEC’s description of an event study explicitly models a stock return against market and, where useful, industry return. That supports recording these controls; it does *not* establish a tradable prediction. | **Evidence-backed conditioning variable**; thresholds require tournament evidence. |
| 3. Tradeability first | Underlying must have fresh NBBO/last-sale data, an explicit maximum relative spread, sufficient displayed liquidity / dollar volume, and a permitted price range. If options are involved, record option bid/ask, spread, quote age, open interest, and contract multiplier separately. | SEC market-information material identifies best quote, last-sale price, and volume as core public market data; Rule 605 execution-quality guidance defines effective spread against the NBBO midpoint. Intraday research using order-book data shows that transaction cost and price impact can materially change apparent results. | **Evidence-backed process control**. No entry is valid on stale or non-executable quotes. |
| 4. Opening and intraday state | Record opening-auction reference, gap versus prior close, first completed opening range, VWAP, and time since open. Do not treat pre-open price or an unclosed candle as a completed signal. | NYSE describes the opening auction as a major price-discovery/liquidity event; its public imbalance information begins before the open and the open can be unusually volatile after overnight news. | **Evidence-backed reason to model the state**, not proof that ORB/VWAP has edge. |
| 5. Attention/participation | Relative volume must be computed against a fixed historical baseline matched by time of day, with the formula and lookback frozen before testing. Record trade count and dollar volume where available, not just a visual volume bar. | Public trade price and volume are basic market information, and original research documents recurring intraday patterns in volume, order imbalance, volatility, and spreads. That research does not make raw volume a standalone directional signal. | **Measurement is evidence-backed**; a particular RVOL cutoff is **unvalidated until tournamented**. |
| 6. Mechanically complete entry | Name a finite timeframe and use only completed bars. State the exact price/level condition, direction, entry order assumption, allowable entry window, and a no-trade condition. Examples: a completed 5-minute close through an opening-range boundary *plus* a separately defined retest, or a completed close relative to VWAP. | This prevents hindsight. A rule that cannot identify its first eligible bar cannot be backtested or audited. | **Research-design requirement**; no generic technical trigger is promoted by this document. |
| 7. Defined invalidation and exits | Before entry, specify stop/invalidation price, the order/fill model, target or exit rule, maximum holding time, end-of-day handling, and a rule for halts/quote failure. The maximum risk must be computable from entry and stop. | Actual intraday transaction-cost research computes trade prices using order-book data and price impact rather than mid-price assumptions. That is the minimum standard for evaluating a stop/target rule. | **Research-design and execution-control requirement**. Exact R-multiples require strategy evidence. |
| 8. Portfolio constraints | Fix max concurrent positions, risk per position, daily loss limit, maximum signals per ticker, correlation/sector concentration, and a circuit breaker for missing/stale data. No averaging down or discretionary exception. | These constraints make the strategy’s unit of exposure stable, so results can be compared rather than inflated by changing size. | **Necessary control**, not evidence of profitability. |
| 9. Independent validation | Pre-register parameters and data sources; use a development period, a sealed out-of-sample period, then forward shadow logging. Report number of variants tried, trades, transaction costs/slippage, drawdown, adverse excursion, and performance by catalyst/regime/liquidity cohort. | Bailey, Borwein, López de Prado, and Zhu show that trying even a relatively small number of configurations can create high simulated performance through backtest overfitting, with poor out-of-sample results possible. | **Mandatory promotion gate**. |

## A practical state machine

```text
PUBLIC, TIME-STAMPED CATALYST
        +
MARKET/SECTOR CONTEXT ──> liquid + fresh underlying/option quotes?
                                      │ no → coverage debt / no trade
                                      ▼ yes
OPENING + PARTICIPATION STATE ──> pre-registered completed-bar setup?
                                      │ no → observe / log only
                                      ▼ yes
DEFINED ENTRY + STOP + EXIT ──> portfolio and data-health constraints pass?
                                      │ no → reject with first failing gate
                                      ▼ yes
SHADOW CANDIDATE ──> separately validated OOS + forward evidence?
                                      │ no → shadow-only
                                      ▼ yes
ELIGIBLE FOR A CONTROLLED, SEPARATE PROMOTION REVIEW
```

## What the scanner should call an A+ candidate today

Until a particular setup is validated, use the narrower label **"A+ process candidate"** rather than **"A+ trade."** It must have every field below at the signal timestamp:

1. Catalyst source and event timestamp, or an explicit `no_verified_catalyst` label.
2. Underlying/option quote age, bid, ask, relative spread, and liquidity pass/fail.
3. Market/sector regime snapshot.
4. Time of day; opening-range/VWAP state; fixed RVOL measurement.
5. Completed-bar setup name and all rule inputs, including the first eligible bar.
6. Entry reference, invalidation, exit/time-stop, and maximum loss estimate.
7. Position and daily-risk gate outcome.
8. Model/version, data provenance, and an immutable observation record.

Missing information is a **reject or a visible coverage debt**, never a discretionary fill-in. A high score cannot compensate for a missing catalyst timestamp, stale quote, unclosed-bar trigger, undefined stop, or lack of out-of-sample evidence.

## Research claims we must not make

- News/catalysts, VWAP, opening ranges, relative volume, EMA crosses, FVGs, order blocks, GEX, or unusual options activity are **not** individually proven A+ strategies by the sources below.
- A screenshot of a profitable option position does not reveal entry time, fill price, stop, exposure, loss history, or selection frequency.
- A historical chart signal does not establish a tradeable return unless it includes bid/ask-aware costs, survivorship-safe universe construction, no look-ahead, and an out-of-sample/forward test.
- Perfect prediction is impossible; improving the system means reducing unmeasured assumptions and classifying every miss, not eliminating uncertainty.

## Source notes (primary / original sources)

1. U.S. Securities and Exchange Commission, [Regulation FD final rule](https://www.sec.gov/files/rules/final/33-7881.htm). It states the simultaneous/prompt public-disclosure standard for covered material nonpublic information and identifies Form 8-K or broad non-exclusionary dissemination as mechanisms. Supports catalyst provenance and timestamp requirements.
2. U.S. Securities and Exchange Commission, [Advisory Committee on Market Information final report](https://www.sec.gov/divisions/marketreg/marketinfo/finalreport.htm). Defines real-time quote interest and completed trade price/volume as essential market information and explains their role in price discovery/best execution. Supports quote and trade-data requirements.
3. NYSE, [Opening and Closing Auctions fact sheet](https://www.nyse.com/publicdocs/nyse/markets/nyse/NYSE_Opening_and_Closing_Auctions_Fact_Sheet.pdf) and [Opening Imbalance History description](https://www.nyse.com/data-insights/nyse-introduces-the-enhanced-nyse-auction-tool-with-opening-imbalance-history). These describe opening-auction price discovery, opening imbalance information, and timing. Supports treating the open as a separate state rather than a normal bar.
4. NYSE, [When Volatility Calls, NYSE DMMs Answer](https://beta.nyse.com/data-insights/when-volatility-calls-nyse-dmms-answer). NYSE reports that overnight news is associated with especially high volatility after the opening auction and that spreads widen as volatility rises. Supports stricter execution gates around high-volatility opens; it does not validate direction.
5. Tirthankar C. Patnaik and Susan Thomas, [*Profitability of Trading Strategies on High-Frequency Data, with Trading Costs*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=568363) (original research paper). Uses intraday order-book data and actual executable-price/impact calculations, explicitly addressing transaction costs and bid-ask bounce. Supports bid/ask-aware backtests.
6. David H. Bailey, Jonathan Borwein, Marcos López de Prado, and Qiji Jim Zhu, [*Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659) (original research paper). Finds high simulated performance can be produced by searching configurations and warns of degraded out-of-sample performance. Supports preregistration, variant counting, sealed OOS data, and forward shadow validation.
7. U.S. Securities and Exchange Commission, [event-study explanation](https://www.sec.gov/files/litigation/litreleases/lr19062-m.pdf), p. 4 n.11. It describes measuring a security’s return relative to a market model, possibly including an industry index. Supports market and sector controls as recorded variables.
8. Michael Ederington and Jae Ha Lee, [*How Markets Process Information: News Releases and Volatility*](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1993.tb04750.x) (original research paper). Finds concentrated price adjustment around scheduled macro announcements and elevated post-announcement volatility. Supports capturing the source/time and treating a catalyst as an event window, not a headline prediction.
9. Lisa K. H. Heston, Robert A. Korajczyk, and Ronnie Sadka, [*Intraday Patterns in the Cross-section of Stock Returns*](https://arxiv.org/abs/1005.3535) (original working paper). It documents recurring intraday patterns in volume, order imbalance, volatility, and spreads, but does not find those variables explain return continuation. Supports measuring relative volume as context rather than treating it as a standalone A+ trigger.
10. U.S. Securities and Exchange Commission, [Rule 605 frequently asked questions](https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/frequently-asked-questions-rule-605-regulation-nms). It defines effective spread in relation to the NBBO midpoint and specifies time-stamped execution-quality measurements. Supports use of contemporaneous NBBO, spread, and quote-age fields.
11. David H. Bailey et al., [*The Probability of Backtest Overfitting*](https://escholarship.org/uc/item/4w1110bb) (original research paper). It develops the CSCV/PBO approach and explains why ordinary hold-outs may be unreliable after repeated strategy selection. Supports locked rules, recorded variant count, cost-aware OOS testing, and forward shadow validation.

## Implementation implication

The current system should prioritize a durable **candidate evidence record** and a post-close **first-failing-gate ledger** before expanding signal logic. New setup families should enter only through a separate preregistration and shadow tournament. Promotion requires repeatable, cost-aware results across independent periods and transparent failure cohorts—not one day, one ticker, or one trader’s reported return.
