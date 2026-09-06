# A+ Scanner: Unexplored Edge Gap Analysis

**Date:** 2026-08-30  
**Scope:** Research and shadow-testing recommendations only. This note does not authorize orders, alter ranking, or claim profitability.

## Executive conclusion

The highest-value next work is **not another indicator or a broader parameter search**. The repository already has extensive price-pattern, level, regime, catalyst, options, calibration, and move-recall machinery. The most incremental opportunities are:

1. measure **how much economic value the ranking left on the table**, not only whether it detected a move;
2. make “A+” conditional on an **actually executable option contract** at a fresh OPRA NBBO;
3. test a **multivariate lead/lag and breadth-acceleration state**, rather than reviving the already-rejected one-leader/one-lag rules;
4. add an **online change-point / abstention layer** so a stale regime label cannot create false confidence during transitions;
5. add **opening-auction and overnight-inventory context** for the first part of the session.

True order-flow features are potentially useful, but they should be a timing/veto challenger, not a new magic score. The original order-flow literature shows a strong relation between order-book-event imbalance and short-horizon price changes; it does not by itself establish profitable prediction after costs. [Cont, Kukanov, and Stoikov, *The Price Impact of Order Book Events*](https://arxiv.org/abs/1011.6402)

## What is genuinely incremental relative to this repository

| Area | Current repository evidence | Actual gap |
|---|---|---|
| Daily move accountability | `scripts/detection_scorecard.py` measures discovery/actionable recall@10, latency, and miss partitions. `research/MOVE_GROUND_TRUTH_SPEC_2026-08-20.md` defines causal move labels. | No magnitude-weighted ranking utility, nDCG/regret, or “best achievable candidate versus chosen candidate” loss across the full tradable universe. |
| Option executability | `research/DATABENTO_OPRA_CANDIDATE_NBBO_PROTOCOL_2026-08-03.md` and `research/OPTIONS_NBBO_CURRICULUM_PREREGISTRATION_2026-08-03.md` define a sound historical CBBO replay. | No complete real-time contract-feasibility gate joined to every spotlight candidate; fill probability and realized slippage are not learned from submitted shadow limits. |
| Cross-asset lead/lag | Five simple frozen hypotheses were already rejected after costs (`research/NOVEL_INFORMATION_EDGE_RESULTS_2026-08-04.md`). | A causal multivariate *state* based on futures impulse, cross-sectional breadth acceleration, and quote-flow agreement has not been tested. This is different from another static pairwise lag search. |
| Probability quality | `scripts/probability_calibration.py` and `scripts/grade_probability_service.py` already implement expanding calibration, Brier metrics, isotonic/Platt methods, and bootstrap bounds. | Candidate-level abstention under regime change and explicit uncertainty widening when the feature distribution shifts are still missing. |
| Regime transitions | Static/rolling regime labels exist. | No Bayesian online change-point detector or equivalent run-length probability was found in `scripts/` or first-party `research/`. |
| Auction state | Levels, ORB, gap, and overnight concepts exist. | No Nasdaq NOII/auction-imbalance or indicative-clearing-price integration was found. |
| Microstructure | MES OFI/absorption research exists; one frozen absorption conjunction produced zero candidates. | No narrow, live challenger combining order-book depletion/replenishment, microprice, and cross-asset OFI at decision time. |

## Ranked recommendations

### 1. Full-universe economic ranking regret — highest priority

**Build in shadow:** For every session, create a point-in-time candidate set at each five-minute decision timestamp and join it after the fact to executable outcomes. In addition to recall@K, report:

- `oracle_best_R - selected_R` and `oracle_best_net_premium_return - selected_net_return`;
- magnitude-weighted recall (larger clean moves count more, but only after causal opportunity timestamps);
- nDCG@5/@10 with realized, cost-adjusted R as graded relevance;
- discovery regret, confirmation regret, execution-gate regret, and rank regret separately;
- the feature delta between the highest-ranked candidate and the best later-resolved candidate.

Discounted cumulative gain was designed to evaluate the usefulness of graded items by rank, making it a better fit than hit-rate alone for “did our best ideas appear near the top?” [Järvelin and Kekäläinen, *Cumulated Gain-Based Evaluation of IR Techniques*](https://dl.acm.org/doi/10.1145/582415.582418)

**Why this is first:** It directly answers the user’s recurring problem—visible moves occurred, but the system either did not discover them, did not rank them, confirmed too late, or rejected a tradeable contract. Without this decomposition, adding features can increase noise without fixing the actual bottleneck.

**Retail feasibility:** **High.** Uses existing bars, ledgers, and outcomes. Main work is causal joins and metrics, not a new paid feed.

**Promotion evidence:** At least 30 independent sessions; frozen universe; improvement in net nDCG/regret on a chronological holdout; no degradation in recall, data coverage, or realistic transaction-cost treatment.

### 2. Real-time option contract feasibility and shadow limit fills

**Build in shadow:** An equity/ETF setup may be A+ structurally but non-executable as a 0DTE option. At candidate time, freeze the exact OCC contract and record:

- OPRA NBBO timestamp/age, bid, ask, midpoint, width in dollars and percent of midpoint;
- displayed size, last-trade age, volume/open interest, Greeks timestamp, expiration/settlement metadata;
- underlying quote age and option/underlying timestamp skew;
- marketable-buy cost at ask, executable exit at bid, and stressed round trip;
- simulated resting-limit prices (mid, one-tick improvement, escalating limit), whether/when subsequent quotes would have made each limit marketable, and adverse selection after that event;
- “unavailable” when OPRA data or synchronization is missing—never infer premium from the underlying.

Alpaca explicitly distinguishes its free **indicative** option feed from actual OPRA quotes and describes OPRA as the consolidated BBO available to subscribed users. [Alpaca Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data) Databento distinguishes event-space CMBP-1/TCBBO from time-sampled CBBO and documents MBO/MBP depth, trades, auction imbalance, and status schemas. [Databento schema guide](https://databento.com/docs/schemas-and-data-formats/cbbo) The SEC’s modernized Rule 605 framework emphasizes execution price, speed, fill rate, effective/quoted spread, realized spread, and size improvement—useful templates for the shadow-fill scorecard even though Rule 605 is an equities disclosure rule. [SEC Rule 605 amendments](https://www.sec.gov/newsroom/press-releases/2024-32)

**Why this matters:** It prevents a visually excellent underlying setup from receiving the same grade as a contract with stale quotes, a 20–40% spread, or no realistic exit. It also supplies the missing evidence for whether patient limits improve fills or simply select adverse moves.

**Retail feasibility:** **Medium-high** if OPRA entitlement already exists; **medium-cost** for historical CBBO. The repository’s cost-capped exact-contract Databento workflow is the correct base.

**Promotion evidence:** Freshness and synchronization coverage ≥90%; at least 100 shadow candidates and 30 dates; positive expectancy at executable sides and stressed fees; fill-policy evaluation frozen before outcomes; no midpoint-as-fill assumptions.

### 3. Multivariate futures lead/lag plus breadth acceleration

Do **not** reactivate the rejected SPY/QQQ/HYG/TLT/VIX one-factor rules. Test a new, tightly preregistered challenger whose input is the *change in market participation*:

- ES and NQ 1m/5m return impulse and quote-flow imbalance known before the equity decision;
- QQQ-minus-SPY and sector-ETF relative return **acceleration**, not just level;
- fraction of the frozen universe above VWAP and its first/second difference;
- advancing-minus-declining dollar volume and new intraday highs-minus-lows velocity;
- mega-cap contribution versus equal-weight breadth, to distinguish index movement from broad participation;
- agreement/disagreement state (for example, NQ impulse up while QQQ breadth acceleration falls).

Hasbrouck’s original intraday price-formation study found that most S&P 500 and Nasdaq-100 price discovery in its sample occurred in E-mini markets and that E-mini price changes generally led regular futures and ETFs. This supports testing causally timestamped futures inputs, not assuming a timeless fixed lag. [Hasbrouck, *Intraday Price Formation in U.S. Equity Index Markets*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=252304) CME offers real-time top-of-book, trade, and market-statistics data through a WebSocket API, with top-of-book messages conflated to 500 ms. [CME Real-Time Futures and Options Data API](https://www.cmegroup.com/market-data/real-time-futures-and-options-data-api.html) NYSE Daily TAQ provides consolidated U.S. equity trades, quotes, and NBBO history for research-quality breadth reconstruction. [NYSE Daily TAQ](https://www.nyse.com/data-products/catalog/daily-taq)

**Retail feasibility:** **Medium.** A Python stream aggregator is straightforward; correct entitlements, clock synchronization, and point-in-time universe history are the real work.

**Promotion evidence:** Freeze no more than a handful of states; compare against the current scanner with the same decision times; multiple-testing correction; locked chronological holdout; demonstrate incremental lift over price/volume-only features after costs.

### 4. Online change-point probability plus an abstention gate

**Build in shadow:** Run an online change-point model over a small vector—index return, realized volatility, breadth acceleration, spread/depth, and volume surprise. Persist:

- posterior probability of a new regime;
- posterior run length;
- pre/post-change feature means;
- how much the calibrated setup probability should be widened or marked unavailable during transition.

Bayesian Online Changepoint Detection computes the posterior distribution of the current run length and supports exact online inference under its model assumptions. [Adams and MacKay, *Bayesian Online Changepoint Detection*](https://arxiv.org/abs/0710.3742)

This should **not** create trades. It should decide whether the existing historical calibration is locally applicable. When change probability or ensemble disagreement is high, the system should abstain from calling a setup A+ until the post-change sample becomes credible. Existing Brier/isotonic/Platt infrastructure remains useful: Brier’s proper probability score provides the base evaluation, while reliability diagrams diagnose whether stated probabilities match observed rates. [Brier, *Verification of Forecasts Expressed in Terms of Probability*](https://journals.ametsoc.org/doi/abs/10.1175/1520-0493%281950%29078%3C0001%3AVOFEIT%3E2.0.CO%3B2) [Niculescu-Mizil and Caruana, *Predicting Good Probabilities with Supervised Learning*](https://icml.cc/Conferences/2005/proceedings/papers/079_GoodProbabilities_NiculescuMizilCaruana.pdf)

**Retail feasibility:** **High** computationally; **medium** statistically because hazard rate and likelihood choices can overfit.

**Promotion evidence:** Pre-register the hazard model; measure detection delay and false alarms; require better chronological Brier skill and lower drawdown/false-positive rate than the same model without abstention.

### 5. Opening-auction imbalance plus overnight-inventory state

**Build in shadow:** Restrict this lane to the open. Join:

- Nasdaq NOII imbalance shares/direction, paired shares, near/far price, and current reference price from 09:25–09:30 ET;
- overnight ES/NQ return, range, volume, and signed flow;
- SPY/QQQ premarket gap and volume;
- distance between indicative clearing price, prior close, overnight extremes, and first regular-session quote;
- whether the opening print resolves or conflicts with overnight inventory.

Nasdaq’s TotalView specification states that NOII begins at 09:25 for the open, increases to one-second dissemination near the cross, and includes paired shares, imbalance shares/direction, near/far prices, and current reference price. [Nasdaq TotalView-Aggregated specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/TVAggSpecification.pdf) Nasdaq describes NOII as the best publicly available predictor of its opening and closing prices because it includes non-displayable as well as displayable order types. [Nasdaq TotalView-ITCH 5.0 specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification_5.0.pdf) Databento also lists an `imbalance` schema for auction imbalance/NOII-type data, subject to dataset availability. [Databento schema guide](https://databento.com/docs/schemas-and-data-formats/cbbo)

**Retail feasibility:** **Medium-low** because real-time auction data is subscription-dependent; high for overnight features already available from futures and premarket bars.

**Promotion evidence:** Evaluate opening setups separately; freeze the 09:25–09:35 window; require incremental holdout lift over gap/ORB/overnight features without NOII.

## Sixth-priority challenger: order-flow depletion/replenishment

Use MBO or MBP-10 to compute causally:

- multi-level OFI;
- microprice and microprice-minus-mid;
- bid/ask depletion and replenishment rates;
- cancellation-to-add ratio;
- spread/depth shock;
- cross-impact agreement between ES/NQ and SPY/QQQ.

Databento documents MBO as every order-book event keyed by order ID, MBP-10 as price-level depth, and its imbalance/status schemas as auction/trading-state data. [Databento schema guide](https://databento.com/docs/schemas-and-data-formats/cbbo) This is richer than the repository’s OHLC/one-level proxies. However, because the existing frozen MES absorption rule emitted zero candidates and because OFI can be primarily contemporaneous, this lane should start as a **confirmation/veto feature** with a narrow preregistration—not a broad threshold search.

**Retail feasibility:** **Medium-low** for equities due feed volume and licensing; **medium** for a small futures/ETF symbol set. Storage and replay discipline matter more than model complexity.

## Recommended build order

| Order | Deliverable | Expected information gain | Data cost | Overfit risk |
|---:|---|---|---|---|
| 1 | Economic ranking-regret report | Very high | Low | Low if labels/spec remain frozen |
| 2 | Real-time OPRA contract-feasibility sidecar + shadow limits | Very high | Medium | Medium |
| 3 | BOCPD transition/abstention challenger | High | Low | Medium; freeze hazard/likelihood |
| 4 | Multivariate futures + breadth-acceleration challenger | High | Medium | High unless hypotheses are few and frozen |
| 5 | NOII/overnight opening lane | Medium-high at the open | Medium/high | Medium |
| 6 | MBO/MBP-10 flow challenger | Uncertain but genuinely new | Medium/high | High |

## What not to add now

- another RSI/EMA/VWAP combination;
- another large parameter sweep over the same OHLCV history;
- social popularity or trader screenshots as rank-positive evidence;
- “AI confidence” that is not a chronologically calibrated probability;
- midpoint option returns or underlying-derived option returns;
- a black-box ensemble before ranking regret identifies which stage is failing.

The disciplined target is not “never miss a move.” It is: **maximize causal, executable top-K opportunity capture while measuring every miss, every false positive, and every unit of ranking regret.**
