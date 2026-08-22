# A+ Entry, Exit, Pattern, and Timeframe Evidence Spec

Date: 2026-08-22

Status: active shadow-only research specification

Authority: manual review only; no order authority

Machine-readable companion: `research/aplus_timeframe_matrix.json`

## 1. Decision standard

“A+” means the strongest observable setup-quality bucket in this dashboard. It does **not** mean a guaranteed winner, a calibrated win probability, or permission to trade. A pattern name alone can never produce A+.

An A+ review candidate requires all of the following:

1. A causal pattern built only from completed bars.
2. A mechanically defined trigger, entry zone, and structural invalidation.
3. Agreement among the timeframes assigned to trigger, confirmation, structure, and regime roles.
4. Participation evidence such as time-adjusted RVOL; OHLCV proxies must never be mislabeled as true order flow.
5. A fresh quote, acceptable spread, adequate liquidity, and post-friction reward/risk.
6. No active anti-pattern, stale-feed, macro-event, halt, or higher-timeframe conflict veto.
7. An explicit exit plan before entry: invalidation, structural objectives, R references, and a locally testable time stop.
8. Local forward outcomes sufficient to calibrate the setup family. Until then, the grade remains a research ranking rather than a probability.

## 2. What the evidence supports

- Systematic pattern recognition is more defensible than subjective drawing. Lo, Mamaysky, and Wang found that several automatically recognized daily patterns changed conditional return distributions, but described them only as incremental information with possible practical value—not guaranteed profit. [NBER working paper](https://www.nber.org/papers/w7613)
- The first and last half hours have distinct information and liquidity behavior. Gao, Han, Li, and Zhou found that the first half-hour market return predicted the last half-hour return in their U.S. ETF sample, with stronger effects on high-volume, high-volatility, and major-news days. The reported out-of-sample explanatory power was meaningful but modest, so 30-minute session state is context, not certainty. [Journal of Financial Economics](https://www.sciencedirect.com/science/article/pii/S0304405X18301351)
- Five-minute sampling is a defensible compromise for intraday risk measurement. A broad realized-volatility study notes that it is difficult to beat five-minute realized volatility, while microstructure research explains why sampling ever faster can increase noise bias. [Review of Financial Studies](https://academic.oup.com/rfs/article/31/7/2729/5001472), [Review of Economic Studies](https://academic.oup.com/restud/article-abstract/75/2/339/1620899)
- Short-horizon price changes are related to order-flow imbalance and inversely related to depth. Because the current feed lacks tick/MBO classification, the dashboard must label signed OHLCV participation as a proxy and withhold “true order flow.” [Journal of Financial Econometrics](https://academic.oup.com/jfec/article-abstract/12/1/47/816163)
- Unusual volume can contain information, but the cited high-volume premium is a daily/weekly-to-monthly result, not proof that any intraday volume spike is an edge. RVOL is therefore confirmation, never a standalone entry. [Duke / Journal of Finance](https://scholars.duke.edu/publication/773086)
- A 15-minute flag detector combined with 15-minute and daily EMA context has published market-specific support. This justifies testing multi-timeframe confirmation, not importing its returns as our expected performance. [Expert Systems with Applications](https://www.sciencedirect.com/science/article/pii/S0957417417301823)
- Stop-loss rules are regime dependent: they reduce expected return under a random walk in the Kaminski–Lo framework but can add value under momentum. Stops must represent setup invalidation and be validated by family/regime; no universal percentage stop is presumed optimal. [SSRN paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338)
- Stop execution price is not guaranteed. A triggered stop generally becomes a market order and can fill far from its stop price; stop-limit orders can fail to execute. The dashboard therefore treats its invalidation as decision geometry, not a fill promise. [FINRA order types](https://www.finra.org/investors/investing/investment-products/stocks/order-types), [FINRA stop-order risks](https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets)
- Opening and closing auctions concentrate price discovery and liquidity. Session-open and session-close setups require special spread/slippage handling rather than ordinary midday assumptions. [NYSE auction fact sheet](https://www.nyse.com/publicdocs/nyse/markets/nyse/NYSE_Opening_and_Closing_Auctions_Fact_Sheet.pdf), [NYSE closing-auction research](https://www.nyse.com/data-insights/closing-auction-immediate-market-impact-price-drift-and-transaction-cost-of-trading)
- 0DTE near-the-money options become extremely sensitive to underlying moves as expiry approaches. Underlying-chart quality is necessary but insufficient: contract spread, liquidity, IV, Greeks, and limited-risk construction must remain separate gates. Gross option volume must not be converted into a dealer-gamma claim. [Cboe 0DTE resources](https://www.cboe.com/tradable-products/0dte), [Cboe positioning study](https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact/)
- Testing thousands of variants creates false discoveries. Every family and threshold must remain preregistered, walk-forward, cost-adjusted, and corrected for multiple testing. [Sullivan–Timmermann–White](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00163), [Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)

## 3. Timeframe roles

| Timeframe | Role | Use | Never use it for |
|---|---|---|---|
| 1m | Optional execution refinement | Fine entry timing after a valid 5m trigger; spread and microstructure check | Standalone A+ pattern grade |
| 5m | Primary intraday trigger | Completed-bar reclaim, break/retest, sweep/MSS, CISD, compression, VWAP trigger | Long-horizon regime |
| 15m | Trigger confirmation | Reject one-bar noise; confirm continuation/reversal structure | Exact fill assumption |
| 30m | Session state | Opening range, initial balance, first/last-half-hour state | Universal directional forecast |
| 60m | Structure bias | Intraday trend, major swing, higher-timeframe FVG/structure | Micro entry trigger |
| 1d | Daily regime | Gap, trend/range regime, major support/resistance, catalyst backdrop | Intraday timing |
| 1w | Major structure advisory | Large swing levels and broader regime | Required intraday trigger |

For U.S. cash equities, 4h bars do not divide the 6.5-hour regular session cleanly. The dashboard therefore uses 60m plus daily for cash-equity structure. A 4h role may be tested separately for nearly continuous futures, but must not be silently mixed into the equity model.

The current equity implementation fetches broker-supported 15m, 30m, 60m, daily, and weekly completed context. It derives 15m/30m/60m from completed 5m bars when that source is fresher. Incomplete aggregation buckets are discarded, and session aggregation is anchored to 09:30 ET.

## 4. Universal entry sequence

Every setup family is evaluated in this order:

1. **Context:** daily regime, 60m structure, session location, catalyst/macro windows.
2. **Level:** causal range boundary, VWAP, confirmed swing, prior-session level, or pattern neckline.
3. **Event:** break, sweep, compression expansion, reclaim, rejection, or displacement.
4. **Confirmation:** completed 5m close plus 15m/30m agreement appropriate to the family.
5. **Entry geometry:** trigger and bounded entry zone; no chasing outside the zone.
6. **Invalidation:** price level proving the setup thesis wrong, with no widening after entry.
7. **Tradability:** live/recent quote, spread, liquidity, RVOL, and post-friction R:R.
8. **Manual decision:** READY_TO_REVIEW is advisory; Kenny decides whether to execute.

## 5. Setup family playbooks

### 5.1 Opening-range break and retest

- Context: daily and 60m direction are non-conflicting; first 30 minutes define session range.
- Trigger: completed 5m close outside the range, followed by a retest that closes back in breakout direction.
- Confirmation: participation expansion and 15m direction not opposed.
- Invalidation: opposite side of retest structure or a decisive close back inside the range.
- Objectives: next confirmed liquidity/structure, then 1R and 2R reference levels.
- Reject: naked opening spike, no retest, weak participation, excessive spread, or immediate failed break.

### 5.2 Catalyst gap continuation

- Context: verified fresh catalyst, liquid security, gap not already path-exhausted, market/sector agreement measured separately.
- Trigger: completed opening range break or controlled pullback/reclaim; never a market-on-open chase.
- Invalidation: pullback low/high or opening-range failure.
- Exit: structural target first; faster time stop if catalyst impulse stalls.
- Reject: unverified social headline, halt risk, spread expansion, crowded extension, or catalyst already stale.

### 5.3 Trend pullback / VWAP reclaim or reject

- Context: 60m/daily trend or a clearly identified range regime.
- Trigger: controlled pullback to a causal mean/level, then completed 5m resumption close; 15m confirms control.
- Invalidation: confirmed swing beyond the pullback, not an arbitrary percentage.
- Exit: prior impulse extreme, next structure/liquidity, then R references.
- Reject: midrange chop, flat participation, repeated VWAP crossings, or late chase beyond the preregistered ATR distance.

### 5.4 Liquidity sweep, market-structure shift, retest

- Context: causal prior-session/opening-range or confirmed swing level; 60m/daily not strongly opposed.
- Trigger: price trades through the level, closes back through it, displaces through local structure, then holds the retest.
- Invalidation: sweep extreme.
- Exit: opposing liquidity and structural levels; do not invent probabilities for a level being swept.
- Reject: wick-only “shift,” future-confirmed pivot, absent displacement, or level derived from an unfinished period.

### 5.5 CISD / FVG sequence

- Context: completed higher-timeframe gap/structure only.
- Required chronology: HTF context → third-candle range → liquidity sweep → chronological inversion/FVG event → body-close change in delivery.
- Trigger: mapped 5m confirmation; 1m may refine only after the 5m sequence is valid.
- Invalidation: model anchor/sweep extreme.
- Exit: opposing range extreme or causal liquidity; social win-rate claims remain excluded until independently reproduced.
- Reject: stages out of order, wick-only body confirmation, missing HTF context, or reused future bars.

### 5.6 Compression breakout / flag continuation

- Context: directional impulse and daily/60m trend compatibility.
- Trigger: range contraction followed by completed expansion with participation; for flags, resumption through the flag boundary.
- Invalidation: opposite side of compression/flag.
- Exit: measured structure can be logged as a hypothesis, while 1R/2R remain neutral comparison points.
- Reject: breakout without volume, overly deep countertrend retracement, or immediate close back inside.

### 5.7 Double top/bottom and head-and-shoulders

- Context: confirmed causal pivots with tolerance scaled by ATR, not visual hindsight.
- Trigger: completed neckline break; optional retest is preferred for manual execution.
- Invalidation: right shoulder/second extreme.
- Exit: next structure plus pattern-height projection recorded as separate targets.
- Reject: unconfirmed right-side pivot, excessive asymmetry, no neckline close, or strong opposing daily trend.

### 5.8 Failed breakout reversal

- Context: genuine prior range and attempted break.
- Trigger: completed close back through the broken boundary, followed by inability to reclaim it.
- Invalidation: failed-break extreme.
- Exit: range midpoint then opposite boundary, subject to post-friction R:R.
- Reject: failure identified before the confirming close or reversal directly into fresh catalyst momentum.

### 5.9 Mean reversion

- Context: explicitly classified range/transition regime; no strong trend or fresh catalyst impulse.
- Trigger: rejection/reclaim at a causal range extreme or VWAP after extension normalizes.
- Invalidation: range extension beyond the rejected extreme.
- Exit: VWAP/range midpoint, then opposite range edge only if conditions persist.
- Reject: trend regime, accelerating order-flow proxy, expanding volatility, or “averaging down.”

### 5.10 0DTE options overlay

- Grade the underlying setup first using the full matrix.
- Separately require current option NBBO, spread percentage, volume/open interest, IV/Greeks, time to expiry, and defined maximum loss.
- Treat call wall, put wall, gamma flip, and dealer regime as unavailable unless a provenance-gated options surface supports them.
- Never infer net dealer gamma from gross calls/puts or social screenshots.
- Underlying invalidation controls the thesis; contract loss behavior and slippage are additional risks.

## 6. Exit framework

No single exit is assumed optimal across all regimes. Each candidate carries:

- **Hard thesis invalidation:** exit/stand aside when the causal setup is disproved; never widen.
- **Structural objectives:** nearest favorable confirmed swing, session liquidity, range boundary, or neckline-derived target.
- **R references:** 1R and 2R for comparable outcome logging, not promises.
- **Time stop:** currently six 5m bars / 30 minutes for the primary intraday model, explicitly labeled `research_default_pending_local_validation`.
- **Progress rule:** lack of favorable excursion and loss of structure before the time stop are separate outcome fields.
- **Execution warning:** actual stop/limit behavior and slippage can differ from displayed geometry.

Time-stop candidates must later be compared by family, regime, volatility bucket, and time of day. The resolver should record MFE, MAE, first target touched, invalidation touched, gap-through/slippage, and terminal reason.

## 7. Worst-setup veto library

Any one of these can block A+ readiness:

- stale or missing quote;
- spread above the preregistered limit;
- missing required timeframe coverage;
- higher-timeframe directional conflict;
- failed breakout against the proposed direction;
- late-chase/ATR extension;
- midrange chop or broadening instability;
- weak participation on a claimed breakout;
- insufficient dollar liquidity or RVOL;
- macro event/halt/earnings ambiguity;
- unverified catalyst;
- post-friction R:R below threshold;
- options surface or dealer-flow claim without provenance;
- unfinished bar, future-confirmed pivot, or repainting input.

## 8. Local validation required before probability language

For every pattern family × primary timeframe × direction × regime bucket:

1. Freeze detector version and thresholds before outcomes.
2. Preserve every eligible event, including blocked and missed setups.
3. Resolve outcomes with synchronized bars and realistic spread/slippage.
4. Split chronologically into development and untouched walk-forward periods.
5. Track trades/events, independent dates, expectancy in R, hit rate, MFE, MAE, drawdown, Brier score for any probability estimate, and calibration error.
6. Apply experiment-family/multiple-testing controls.
7. Stress doubled costs, delayed entry, gap-through invalidation, and regime changes.
8. Report abstentions and coverage failures; do not score missing data as neutral.
9. Promote only with independent forward evidence and human approval.

Research priors must stay labeled `RESEARCH_PRIOR` or `UNCALIBRATED`. They cannot populate a current “win probability.”

## 9. Implementation contract

- `execution_enabled=false` and `can_submit_orders=false` on every new output.
- The canonical grade remains the existing pattern rubric; timeframe scans cannot duplicate confluence credit.
- The live panel shows each timeframe’s role, completed-bar count, minimum history, status, and provenance.
- Missing daily/required context adds `incomplete_aplus_timeframe_coverage` and prevents READY_TO_REVIEW.
- The daily A+ audit records timeframe-coverage status and carries unresolved outcomes forward.
- All bars are completed-period observations. 1m is optional execution refinement and is never a standalone A+ grade.

## 10. Primary sources reviewed

1. Lo, Mamaysky, Wang, *Foundations of Technical Analysis*: https://www.nber.org/papers/w7613
2. Gao, Han, Li, Zhou, *Market Intraday Momentum*: https://www.sciencedirect.com/science/article/pii/S0304405X18301351
3. Gao et al., *Hedging Demand and Market Intraday Momentum*: https://www.sciencedirect.com/science/article/pii/S0304405X21001598
4. Bollerslev et al., *Risk Everywhere*: https://academic.oup.com/rfs/article/31/7/2729/5001472
5. Bandi and Russell, *Microstructure Noise, Realized Variance, and Optimal Sampling*: https://academic.oup.com/restud/article-abstract/75/2/339/1620899
6. Cont, Kukanov, Stoikov, *The Price Impact of Order Book Events*: https://academic.oup.com/jfec/article-abstract/12/1/47/816163
7. Gervais, Kaniel, Mingelgrin, *The High-Volume Return Premium*: https://scholars.duke.edu/publication/773086
8. Kaminski and Lo, *When Do Stop-Loss Rules Stop Losses?*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338
9. Sullivan, Timmermann, White, *Data-Snooping, Technical Trading Rule Performance, and the Bootstrap*: https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00163
10. Bailey et al., *The Probability of Backtest Overfitting*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
11. Moreira and Muir, *Volatility Managed Portfolios*: https://www.nber.org/papers/w22208
12. Cervelló-Royo et al., filtered intraday flag recognition: https://www.sciencedirect.com/science/article/pii/S0957417417301823
13. Alpaca historical stock bars: https://docs.alpaca.markets/us/reference/stockbarsingle-1
14. FINRA order types: https://www.finra.org/investors/investing/investment-products/stocks/order-types
15. FINRA stop-order risks: https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets
16. NYSE opening/closing auctions: https://www.nyse.com/publicdocs/nyse/markets/nyse/NYSE_Opening_and_Closing_Auctions_Fact_Sheet.pdf
17. Cboe 0DTE resources: https://www.cboe.com/tradable-products/0dte
18. Cboe 0DTE positioning and impact: https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact/
