# Social Setup Audit: H1 SMT/CISD MNQ and Final-Two-Hours SPX 0DTE Iron Fly

Date: 2026-08-24
Status: research complete; both ideas remain non-executable hypotheses
Authority: manual review only; no order authority changed
Source claims: user-supplied screenshots of posts by `@Killa_kellzz` and `@3PeaksTrading` dated 2026-08-24

## Executive decision

| Candidate | Mechanical validity | Independent evidence for the claimed edge | Repo fit | Decision |
|---|---|---|---|---|
| MNQ/NQ: H1 SMT at prior-day low -> 5m CISD -> OB/FVG rejection -> completed-bar entry | Coherent and fully mechanizable after ambiguities are frozen | No primary or peer-reviewed source located that validates this exact sequence or its 1:3 expectancy; the repo's broader sweep/MSS/FVG family previously failed development | Adds the currently missing ES/NQ SMT feature to an existing, still-unvalidated CISD framework | **Preregistered shadow challenger only** |
| SPXW 0DTE: final-two-hours compression -> 15-point short iron fly, 45-50 delta body, $6-$8 credit, no stop | The four-leg payoff is valid and defined-risk; the repo already supports executable-side iron-fly math | No independent support located for 58% wins, Mon/Fri superiority, reliable $6-$8 credits, “no stop,” or the screenshot performance table | Structure support exists; the missing item is a clean timing/regime test using executable complex-order evidence | **Research-only challenger; not A+ or READY** |

Neither screenshot is enough to promote a rule. The correct response is to preserve the reproducible mechanics, refuse the unverified performance claims, and run both against frozen definitions, realistic costs, untouched out-of-sample data, and the existing multiple-testing governance.

## 1. Candidate A — H1 SMT at PDL, then 5m CISD/FVG/OB rejection

### 1.1 What the post claims

The post describes:

1. An H1 “SMT” divergence at a prior-day low (PDL), supplying location and narrative.
2. A move to the five-minute chart to identify the CISD associated with the divergence.
3. Price trading through the CISD level and retracing.
4. A rejection from an order block while respecting a five-minute FVG.
5. A short entry at the close of the completed five-minute rejection bar.
6. Five MNQ contracts, $175 stated risk, $532.50 stated reward, described as 1:3 reward/risk.

The post does not supply a reproducible definition of SMT, the PDL session, the CISD anchor, the order-block construction, the exact FVG bounds, the stop, the entry timestamp, fees, or slippage. Those omissions prevent replication without inventing rules.

### 1.2 What is mechanically valid

- CME specifies MNQ as `$2 x Nasdaq-100 Index` with a 0.25-point minimum tick worth $0.50. Five MNQ therefore carry $10 per index point. The stated $175 risk corresponds to 17.5 MNQ points and $532.50 corresponds to 53.25 points, or about **3.04R gross** before fees and slippage. [CME MNQ contract specifications](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html), [CME Micro E-mini FAQ](https://www.cmegroup.com/articles/faqs/micro-e-mini-equity-index-futures-frequently-asked-questions.html)
- S&P 500 and Nasdaq-100 futures are appropriate instruments for a relative-value feature because the indexes are strongly, but not perfectly, correlated. CME's historical illustration reports a 0.924 correlation and explicitly notes that index composition can produce divergent relative performance. This supports measuring divergence; it does **not** establish a reversal signal. [CME stock-index spread paper](https://www.cmegroup.com/education/whitepapers/stock-index-spread-opportunities)
- Waiting for a completed five-minute rejection close is causal and non-repainting. It matches the repo's existing completed-bar discipline and is safer to test than a wick-in-progress entry.
- “Location -> event -> confirmation -> retracement -> entry” is a valid state-machine design. Each stage can receive a timestamp and be checked for chronological order.

### 1.3 What is not validated

- No CME, regulator, or peer-reviewed source located in this review operationally defines or validates the trading meanings of **SMT divergence, CISD, FVG, or order block**, either alone or in this exact sequence.
- Academic futures research supports the importance of E-mini price discovery, but not this branded signal sequence. [Journal of Banking & Finance price-discovery study](https://doi.org/10.1016/j.jbankfin.2023.106970)
- New York Fed research found order clustering around support/resistance can be associated with reversal or acceleration, but the study concerns foreign exchange and does not validate PDL-based ES/NQ SMT. [Federal Reserve Bank of New York Staff Report 125](https://www.newyorkfed.org/research/staff_reports/sr125.html)
- A gross 3R target is payoff geometry, not expected value. Win probability, no-fill probability, slippage, stop gaps, commissions, and the complete distribution of losing trades determine expectancy.
- The repo has already found the broader sweep/MSS/FVG sequence negative on SPY, QQQ, and MES in development, with only 26 MES occurrences. This stricter H1-SMT-at-PDL composite may behave differently, but it cannot inherit a positive prior from that failed family. See `research/GLOBAL_SOCIAL_SEQUENCE_RESULTS_2026-08-19.md`.
- The repo's ICT audit correctly marks CISD as `unvalidated_pattern_hypothesis` and lists ES/NQ SMT as not shipped. See `research/ICT_MODEL_DEEP_DIVE_2026-08-23.md`.

### 1.4 Frozen definition required before replay

Do not backfill these definitions after inspecting outcomes:

| Element | Required frozen rule |
|---|---|
| Instruments | Tradable MNQ front contract; comparison pair must be declared, preferably synchronized MES/ES versus MNQ/NQ rather than mixing cash indexes and futures |
| Contract roll | Exact roll calendar, roll time, and back-adjustment method; exclude or separately label roll sessions |
| Sessions | Whether PDL is prior RTH low, prior full Globex-session low, or both as separate variants |
| H1 bars | Session-aligned, completed 60-minute bars; no partially formed hourly bar |
| SMT | Which instrument sweeps its declared PDL while the paired instrument does not; maximum time separation; minimum sweep; divergence measured by synchronized returns or ATR-normalized distance, never raw ES-versus-NQ point differences |
| Correlation gate | Rolling lookback, sampling frequency, minimum correlation, quote/bar freshness, and behavior when the relationship breaks |
| CISD | Exact body-close anchor and direction; no wick-only confirmation; stages must occur after the SMT event |
| FVG | Three-completed-bar geometry, minimum size in ticks/ATR, active/unfilled definition, midpoint rule, and maximum age |
| Order block | Mechanical candle selection, displacement requirement, bounds, invalidation, and maximum age |
| Entry | Close of the first completed five-minute rejection bar that satisfies all preceding stages, plus a maximum chase distance |
| Stop | Exact structural level; never infer stop distance backward from a desired $175 risk |
| Targets | Freeze 1R, 2R, 3R and structural targets as separate outcome policies; do not choose the best after replay |
| Time stop | Freeze maximum bars/time and session cutoff |
| Vetoes | CPI, PCE, PPI, NFP, FOMC, GDP, exchange halt/data outage, stale pair bar, low participation, abnormal spread, and higher-timeframe conflict |
| Costs | Contract-specific commissions and exchange fees plus at least one-tick entry and exit slippage; stress at two ticks and on stop-first same-bar ambiguity |

### 1.5 Minimum study

1. Use synchronized point-in-time ES/MES and NQ/MNQ trades or one-minute bars, reconstructed into causal H1 and 5m bars. Preserve RTH and ETH labels.
2. Declare one primary definition. Treat alternate SMT thresholds, PDL sessions, FVG sizes, and exits as one experiment family subject to BH-FDR/multiple-testing correction.
3. Compare against:
   - random entry in the same instrument, time window, and regime;
   - PDL sweep + rejection without SMT;
   - SMT without CISD/FVG/OB;
   - the existing liquidity-sweep/MSS/FVG rule;
   - a simple momentum or VWAP baseline.
4. Report every eligible signal, including duplicates, no-fills, vetoed winners, and failures. Resolve adverse-first when stop and target occur in the same source bar.
5. Minimum evidence before probability language: at least 200 independent events, at least six months untouched out-of-sample, positive post-cost expectancy, positive Brier skill versus base rate, acceptable drawdown, and stability across trend/range and volatility regimes. This does not bypass the repository's stricter promotion gates.

### 1.6 Dashboard/scanner contract

Surface this candidate only as `shadow_only` / `unvalidated_pattern_hypothesis` until the gate passes.

Required fields:

- `strategy_id`, `detector_version`, `spec_hash`, `family_id`, `governance_status`;
- `tradable_symbol`, `comparison_symbol`, contract months, roll status, source labels, source timestamps, and freshness;
- `pdl_session`, `pdl_value`, `pdl_declared_at`, `sweep_symbol`, `sweep_time`, `sweep_ticks`;
- `pair_return_gap`, `pair_atr_normalized_gap`, `rolling_correlation`, `correlation_lookback`;
- `smt_direction`, `smt_confirmed_at`, `h1_bar_closed_at`;
- `cisd_anchor`, `cisd_direction`, `cisd_confirmed_at`, `cisd_body_close_valid`;
- FVG lower/upper/midpoint, formation time, size, fill state, and age;
- order-block bounds, formation time, displacement score, retest time, and rejection-bar close;
- `chronology_valid`, `completed_bars_only`, `detection_latency_ms`;
- exact entry zone/price/time, invalidation, stop distance, quantity-neutral risk per contract, 1R/2R/3R and structural objectives, time stop, and maximum chase;
- estimated commissions, baseline/stress slippage, gross R:R, net R:R, and data-quality/macro/regime vetoes;
- outcome fields: MFE, MAE, target/stop first, time-to-target, exit reason, net P&L, and counterfactual veto result.

Dashboard wording should say **“H1 SMT/CISD composite — research candidate”**, not “A+,” until local evidence earns that label.

## 2. Candidate B — SPXW 0DTE final-two-hours short iron fly

### 2.1 What the post claims

The post proposes a favorite SPX 0DTE setup for “the final two hours” of volatility compression, described as especially good Monday and Friday. It sells a near-ATM 45-50-delta put/call body and buys wings 15 points away, collects roughly $6-$8, uses no stop, and lets the cash-settled position expire. The screenshot claims 58.3% wins and displays backtest metrics including approximately 27.9% CAGR and -15.3% maximum drawdown.

The post does not disclose a reproducible compression formula, a complete entry schedule in machine-readable form, data vendor, complex-order fill model, rejected/no-fill orders, all fees, settlement handling, parameter-search count, in-sample/out-of-sample partition, or an audit trail. The displayed statistics are therefore **unverified social claims**.

### 2.2 What is mechanically valid

- OCC/OIC defines a short iron butterfly as long an upper-strike call, short a call and put at the same middle strike, and long a lower-strike put, with equidistant wings and a common expiration. Its outlook is neutral/narrow-range; time decay helps and increasing implied volatility hurts, all else equal. Maximum profit is the entry credit; maximum loss is wing width minus credit; expiration break-evens are body strike plus/minus the credit. [OCC/OIC short iron butterfly](https://www.optionseducation.org/strategies/all-strategies/short-iron-butterfly)
- SPX has a $100 contract multiplier. SPXW is cash-settled and European-style, and expiring SPXW ordinarily trades until 4:00 p.m. ET. Cash settlement and European exercise remove share-delivery and early-assignment risk; they do not remove market, execution, settlement, or broker risk. [Cboe SPX product page](https://www.cboe.com/tradable-products/sp-500/spx-options), [Cboe SPX specifications](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications/)
- A 15-point fly sold for 6-8 index points has the following **gross expiration bounds per one-lot**, before fees:

| Entry credit | Maximum profit | Maximum loss | Expiration break-evens | Full-win/full-loss break-even win rate |
|---:|---:|---:|---|---:|
| $6.00 | $600 | $900 | body ± 6 | 60.0% |
| $7.00 | $700 | $800 | body ± 7 | 53.3% |
| $8.00 | $800 | $700 | body ± 8 | 46.7% |

The claimed 58% win rate can therefore be losing or profitable depending on actual credit, fill quality, fees, settlement location, and average partial gains/losses. Win rate alone is not expectancy.

- A 45-50 delta body is essentially a near-ATM strike-selection description, not a demonstrated signal edge.
- The repo already implements symmetric four-leg validation, executable-side entry credit, expiration break-evens, max profit, and max risk in `scripts/options_shadow_twin.py`. It also has iron-fly replay support in `research/options_nbbo_curriculum.py`. The payoff primitive is not the gap; the timing/regime hypothesis is.

### 2.3 What is not validated and where the risk hides

- No independent evidence located validates **58% wins, $6-$8 reliably executable credits, Monday/Friday superiority, the displayed CAGR/drawdown, or no-stop superiority** for the stated rule.
- Cboe notes that near-the-money 0DTE options become extremely sensitive to underlying moves as expiration approaches. A short ATM body is therefore exposed to rapidly changing delta/gamma in precisely the period proposed. [Cboe 0DTE resources](https://www.cboe.com/tradable-products/0dte)
- “Defined risk” limits the terminal worst-case payoff, but a 15-wide structure can still lose $700-$900 per one-lot at the stated credits. A gap or late trend can move it rapidly toward maximum loss.
- “No stop” avoids stop-outs and removes stop-rule ambiguity, but it is not intrinsically superior. It concentrates the loss distribution near the defined maximum and can create severe late-day mark-to-market exposure. It must be compared prospectively with frozen profit-take, loss-limit, time-exit, and settlement variants—not selected after seeing results.
- FINRA warns that 0DTE options are highly sensitive to underlying moves and a broker may liquidate a near-expiry position; cash settlement reduces some exercise funding concerns but does not guarantee the broker will allow a position to remain. [FINRA 0DTE investor notice](https://www.finra.org/investors/insights/zeroing-in-options-trading-strategy)
- The SEC's SPXW study documents separate books/auctions for single- and multiple-leg orders and shows that patient customer limit orders can obtain price improvement, while fill probability remains part of the economics. Cboe's complex-order book treats the package as one net-price/ratio order. A backtest must use an executable complex spread or a conservative package bound; summing four mids creates fictional fills and sending legs separately creates leg risk. [SEC DERA SPXW execution study](https://www.sec.gov/files/dera-hope-reasonable-prc-2503.pdf), [Cboe Complex Order Book](https://www.cboe.com/us/options/trading/complex_orders/)
- A recent 0DTE asset-pricing study found that an apparent profitable pricing-bound strategy dissipated after daily 0DTE availability, illustrating regime/integration drift. [Almeida, Freire, and Hizmeri, *0DTE Asset Pricing*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4701401)
- A 2026 *Journal of Finance* paper reports no feasible pseudo-arbitrage after transaction costs, estimation risk, and short-term volatility risk. This does not test the proposed iron fly directly, but reinforces the need for realistic execution. [Chong et al., *Do Equity and Options Markets Agree about Volatility?*](https://doi.org/10.1111/jofi.70070)
- Cboe's own market-position study found no discernible aggregate effect of 0DTE trading on SPX intraday volatility or gap patterns and emphasizes that gross volume is not net dealer exposure. “Compression because of dealer pinning” must never be inferred from volume or open interest alone. [Cboe 0DTE market-impact analysis](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options)

### 2.4 Frozen definition required before replay

| Element | Required frozen rule |
|---|---|
| Product | Same-day PM-settled SPXW only; exact expiration identifier; never substitute SPY or AM-settled SPX |
| Entry time | One exact timestamp or a preregistered causal trigger inside 14:00-15:00 ET; do not optimize every minute and report the winner |
| Compression | Mechanical lookback and metric, such as realized range/ATR percentile, Bollinger width percentile, or forecast remaining variance; specify threshold and require only completed observations |
| Day-of-week | Monday/Friday primary hypothesis versus all-day benchmark; record holidays and half days separately |
| Body | Exact strike selection rule using synchronized call and put delta; specify tie-break and maximum distance from spot/forward |
| Wings | Exactly 15 points on both sides; reject asymmetric or unavailable strikes |
| Credit | Net complex-order credit, not sum of leg mids; freeze minimum/maximum acceptable credit and maximum package spread |
| Order | One four-leg limit order, price-improvement schedule, wait time, cancel/no-fill rule, quote-size requirement, and no legging |
| Exit | Primary “hold to PM settlement” policy plus separately preregistered challengers; define broker cutoff and emergency data/market halt behavior |
| Events | Freeze FOMC, CPI, NFP, PCE, GDP, major scheduled remarks, early close, and unscheduled-news policy |
| Costs | Broker commission, four-leg exchange/regulatory fees, entry package slippage, close cost for non-settlement variants, and stress fills |
| Capital | Per-lot maximum loss, concurrent-risk limit, buying-power treatment, and maximum percent of account risk; do not infer suitability from the post's “small account” claim |

### 2.5 Minimum study

1. Acquire historical SPXW option-chain NBBO with quote timestamps, sizes, Greeks or sufficient inputs to reproduce them, official SPX settlement, and preferably Cboe complex-order book/auction evidence. Underlying bars alone cannot test the strategy.
2. Replay every eligible day, not only days when a desired $6-$8 credit exists. Log no-contract, no-credit, stale-quote, wide-package, no-fill, and broker-cutoff outcomes.
3. Primary fill rule: a marketable package price at or worse than the complex-order quote. Secondary analysis may test patient nonmarketable limit orders with explicit fill/no-fill logic. Never use four-leg midpoint marks as the primary result.
4. Compare the frozen Monday/Friday rule against Tuesday/Wednesday/Thursday, all days, time-matched short iron condor, and no-trade. Segment by VIX/realized-volatility regime, macro day, trend/range state, gap, and entry-credit bucket.
5. Report net expectancy, median and tail P&L, CVaR, max drawdown, profit factor, Sharpe/Sortino, credit capture, fill rate, no-fill opportunity cost, settlement distance, maximum adverse mark, and time below each break-even. Report confidence intervals clustered by trading date.
6. Keep an untouched final holdout and apply BH-FDR/per-family correction to entry-time, compression, weekday, credit, and exit variants. Require rolling revalidation because late-day 0DTE microstructure changes.

### 2.6 Dashboard/scanner contract

Required fields:

- `strategy_id`, `detector_version`, `spec_hash`, `family_id`, `governance_status`, `promotion_eligible`;
- `underlying=SPX`, `expiry`, `settlement_style=PM_cash`, `minutes_to_expiry`, trading-session/holiday state;
- compression metric name, lookback, current value, percentile, threshold, and `compression_confirmed_at`;
- day-of-week hypothesis cohort, macro/news vetoes, trend/range regime, realized volatility, implied move, IV term structure, and source provenance;
- exact OCC symbols for all four legs; call/put, buy/sell, strike, delta, bid, ask, bid/ask size, quote timestamp/age, and source;
- body strike, wing strikes, wing width, net complex bid/ask, package spread, limit credit, executable credit, fill status/time, and no-fill reason;
- aggregate delta/gamma/theta/vega at entry, with methodology and timestamp;
- gross and net max profit/loss, lower/upper expiration break-even, max account-risk percentage, buying-power estimate, fees, and slippage stress;
- exit policy, broker liquidation cutoff, last permitted manual action time, settlement source/value, and fail-closed data behavior;
- outcome fields: package MFE/MAE using executable close sides, SPX path relative to break-evens/wings, terminal settlement P&L, net P&L, exit reason, and regime bucket.

Dashboard wording should say **“SPXW late-day iron-fly challenger — unvalidated”** and separately show:

- structure valid/invalid;
- timing hypothesis satisfied/not satisfied;
- package executable/not executable;
- evidence progress and OOS status;
- `execution_enabled=false` and `can_submit_orders=false`.

## 3. Implementation priority

1. **MNQ composite:** worthwhile as a strictly frozen shadow challenger because H1 location plus normalized ES/NQ divergence is a genuine new feature. It must not add grade weight until it beats simpler ablations and the failed broader sweep/MSS/FVG baseline out of sample.
2. **SPXW iron fly:** lower implementation priority as a new detector because the repo already supports the structure. The highest-value work is data: executable complex-order history, an exact compression definition, all-day/no-fill replay, and honest tail accounting.
3. **No production action:** do not loosen current risk gates, do not enable order submission, do not label either idea A+, and do not quote the social win rate/CAGR as system evidence.

## 4. Acceptance and rejection gates

### Accept for continued shadow collection only if

- every rule is frozen before viewing outcomes;
- point-in-time source data and freshness are retained;
- every eligible, blocked, missed, and no-fill event is logged;
- execution friction is modeled from tradable sides;
- results survive untouched out-of-sample, regime splits, and multiple-testing correction;
- net expectancy and drawdown improve on simpler baselines.

### Reject or quarantine if

- the detector requires subjective chart drawing or hindsight pivots;
- the H1/5m event chronology can repaint;
- raw ES and NQ point changes are compared without normalization;
- the SPX fly uses four-leg mids, assumes fills, or drops no-fill days;
- Monday/Friday or entry time was chosen after testing many variants without correction;
- a social screenshot is used as win-rate, CAGR, or drawdown evidence;
- missing/stale data silently defaults to READY.

## 5. Bottom line

The MNQ post contains a **testable composite**, not a verified edge. Its useful contribution is the proposed H1 relative-divergence location before an existing completed-bar CISD/retest trigger. That is enough to justify a preregistered shadow test, not an A+ badge.

The SPX post describes a **valid payoff structure but an unverified timing strategy**. A 15-wide $6-$8 iron fly has clear bounded economics, yet a 58% win rate is meaningless without the credit and full P&L distribution. Late-day 0DTE gamma, package fills, four-leg fees, no-fill selection, settlement behavior, and tail losses are the edge test. The repo already has the right iron-fly math; it needs executable evidence, not another social-performance claim.
