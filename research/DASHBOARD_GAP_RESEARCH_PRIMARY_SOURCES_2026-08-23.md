# Dashboard Gap Research — Primary Sources

Date: 2026-08-23

Status: implementation research; manual-execution dashboard only

Authority: `execution_enabled=false`; `can_submit_orders=false`

## 1. Executive conclusion

The repository already has unusually strong pieces: completed-bar multi-timeframe analysis, explicit trigger/invalidation/target geometry, a 15-second live-equity quote gate, an A+ daily audit, chronological grade calibration, experiment-family accounting, options-feed provenance, fill-quality reporting, and read-only safety contracts. The main problem is **integration**, not a lack of indicators.

The dashboard should not add more pattern names until it closes four gaps:

1. **One point-in-time decision snapshot:** every displayed grade must bind the same market-data cut, venue coverage, completed bars, quote, plan version, and model version.
2. **One complete denominator:** every eligible, detected, blocked, missed, duplicated, and unresolved setup must have a stable identity and daily lifecycle.
3. **One net-after-cost truth record:** expected and actual entry/exit quality must be measured from executable quotes, including unfilled and partial orders.
4. **One promotion contract:** family/timeframe performance, calibration, multiple-testing penalties, walk-forward evidence, and drift must be visible together before any setup is described with probability language.

“A+” should remain the highest **review-quality** bucket, not a promise, until the exact setup family × asset × timeframe × regime bucket has qualified forward calibration. No research source supports “perfectly timed” or guaranteed winning entries.

## 2. Current-state evidence inspected

The following local artifacts establish the baseline:

- `research/APLUS_ENTRY_EXIT_TIMEFRAME_EVIDENCE_SPEC_2026-08-22.md` already defines completed-bar timeframe roles, geometry, vetoes, post-friction reward/risk, and outcome fields.
- `research/aplus_timeframe_matrix.json` already defines a U.S. cash-equity ladder: 5m trigger, 15m confirmation, 30m session state, 60m structure, daily regime, optional 1m/weekly context.
- `scripts/live_opportunity_engine.py` already labels the configured Alpaca stock feed, blocks quotes older than 15 seconds, checks spreads/RVOL/dollar liquidity, and estimates friction.
- `scripts/live_trading_cockpit.py` already inventories source provenance, quarantines old reports, exposes plan geometry, blocks stale decision cards, attaches only exact family/regime/grade calibration buckets, and prevents unqualified probabilities from ranking.
- `scripts/grade_probability_service.py` already performs chronological expanding-date isotonic calibration, moving-block bootstrap intervals, reliability bins, ECE/MCE, and Brier skill gates.
- `scripts/hypothesis_ledger.py`, `scripts/promotion_gate.py`, and `scripts/adversarial_strategy_audit.py` already provide experiment-family, promotion, PBO, and deflated-Sharpe scaffolding.
- `scripts/daily_aplus_review.py` already enumerates top-tier observations, audits declared sources, preserves unresolved follow-ups, and keeps order authority disabled.
- `scripts/fill_quality_report.py` already decomposes intent-to-arrival, arrival-to-fill, and fill-to-realized slippage for available broker fills.
- Options paths already distinguish `alpaca_opra_nbbo` from `indicative_modified_not_opra_nbbo` and repeatedly warn that indicative data is not OPRA NBBO.

The recommendations below therefore extend or unify these contracts; they do not propose a second grader.

## 3. Prioritized gap register

| Priority | Gap | Current observation | Closure requirement | Acceptance evidence |
|---|---|---|---|---|
| P0 | Point-in-time feed truth is fragmented | The live engine has a strict quote-age gate, while cockpit source health also uses generic 15m/6h/36h labels and 24h quarantine. Feed entitlement is labeled `configured_not_verified`. | Create one feed-quality object carried by every candidate: provider, feed, venue coverage, entitlement verified, event time, received time, decision time, age, delayed flag, clock skew, sequence gaps, session, completed-bar cut, last-good time, and threshold used. | A stale/missing/delayed/sequence-gapped required input deterministically prevents `READY_TO_REVIEW`; IEX and indicative options cannot be presented as consolidated market truth. |
| P0 | Candidate identity is not universal | The A+ review groups by `source + review_id`; fallback IDs include the source and day. The same economic setup can appear under multiple producers, while outcome IDs may not join to fallback IDs. | Define a canonical lifecycle ID from asset, symbol/contract, setup family, direction, causal level, trigger-bar close, detector version, and plan version. Preserve producer IDs as aliases. | Cross-source duplicates collapse into one lifecycle; every outcome either joins exactly once or is visibly `unmatched`; no silent loss. |
| P0 | The complete denominator is not reviewed | The daily A+ audit reviews only explicit A+, canonical A, or score ≥93. Its `system_review_coverage_pct` is 100% of collected top-tier items, not 100% of the eligible scan universe. | Record eligible universe, scans attempted, data failures, all grades, hard-blocked candidates, near misses, A+ candidates, manual executions, and hindsight-discovered missed moves. Separate detection coverage from review coverage. | Daily report reconciles `eligible = evaluated + data_blocked`; `evaluated = emitted + abstained`; all A+ lifecycles are resolved or carried forward. |
| P0 | Display geometry is not an immutable decision record | Trigger, stop, target, and current price are assembled from the latest source values; later snapshots can change the apparent original plan. | Freeze the first actionable plan with `plan_hash`, `plan_version`, trigger, entry zone, maximum chase, structural invalidation, order style, target ladder, time stop, cost assumption, data cut, and no-trade conditions. Later changes append events. | Post-trade review can reproduce exactly what the user saw before entry and compare planned versus actual behavior. |
| P1 | Net-after-cost evidence is incomplete | Fill-quality reporting handles available filled broker orders and often lacks realized price. It does not make unfilled/cancelled/partial orders part of the denominator, and manual fills may be outside this path. | Add decision midpoint, arrival NBBO, order price/type, bid/ask size, fill quantity, fill time, partial/unfilled/cancel reason, fees, effective spread, implementation shortfall, exit NBBO, and net R. Provide a manual-fill capture path with audit timestamps. | A+ ranking and outcome reports show gross R and net R; cost stress and delayed-entry stress can reverse a grade; unfilled attempts remain visible. |
| P1 | Calibration is not yet the single ranking authority | Chronological calibration is strong, but its main bucket key is family/regime/grade. Asset, trigger timeframe, direction, session, holding horizon, data-feed/model version, and cost model can materially change outcomes. | Version predictions before outcomes and report calibration at the finest preregistered bucket supported by data. Use a visible fallback hierarchy when exact buckets are sparse. Include confidence interval, Brier skill, reliability, discrimination, abstention coverage, and drift. | No percentage appears without an exact or explicitly pooled qualified bucket; the dashboard shows sample size, dates, horizon, data cut, calibration version, and fallback level. |
| P1 | Multiple-testing controls are present but not unified with the visible A+ card | Experiment-family size, Bonferroni, PBO, and DSR exist in separate paths. A user cannot see whether a high grade survived the full research family. | Bind detector/spec hash, trial-family ID, variants attempted, chronological folds, untouched test, PBO/DSR, cost stress, and shadow-forward status to the setup-family scorecard. | Promotion fails closed if any tried variant is absent from the family ledger or if the displayed model hash differs from the tested hash. |
| P1 | Multi-timeframe policy is equity-centric | The current matrix explicitly targets U.S. cash equities. Futures have different session boundaries and nearly continuous trading; options require an underlying setup plus contract execution state. | Keep family-specific timeframe roles rather than scanning every interval equally. Add separate frozen matrices for cash equities, index futures, and option overlays, including exchange calendar, RTH/ETH scope, aggregation anchor, roll/expiry behavior, and completed-period rules. | Every family reports context TF, setup TF, trigger TF, optional execution TF, required coverage, conflicts, and outcome statistics for that exact mapping. |
| P2 | Options A+ gating is not fully unified at contract level | OPRA-versus-indicative provenance exists and contracts can be blocked, but underlying grades, symbol-level liquidity, contract selection, and GEX context are assembled across reports. | Require current OPRA NBBO for trade-ready options; otherwise research-only. Bind one exact contract/spread, quote age, bid/ask sizes, OI, volume, IV/Greeks provenance, expiry, event risk, and estimated round-trip friction to the decision snapshot. | An underlying A+ cannot become an options A+ without a qualified contract. Indicative quotes and missing contracts are visibly non-executable research evidence. |
| P2 | GEX can be over-interpreted by users | The cockpit already calls current gamma a proxy/context, but a single sign or wall can still look authoritative. | Label every GEX field `model_estimate`; show source, as-of time, coverage, customer/dealer-sign assumption, open/close assumption, spot/IV/time sensitivity, and uncertainty. Never let GEX alone create or promote an entry. | Removing GEX cannot create a different underlying setup; it may only add context or a veto under a separately validated rule. |
| P2 | Daily review lacks a single decision-quality scorecard | Retro, journal, outcome, calibration, fill quality, and A+ review exist, but they do not form one reconciled close-of-day workflow. | Produce one daily control report covering feed health, scan denominator, A+ lifecycle, manual decisions, rule adherence, planned/actual fills, MFE/MAE, gross/net R, false positives, false negatives, calibration update, drift, and open follow-ups. Threshold retuning must remain outside the daily job. | Day cannot be marked complete while required sources, A+ outcomes, manual-decision fields, or unmatched fills remain unexplained. |

## 4. Primary-source findings by topic

### 4.1 Multi-timeframe scans: assign roles; do not multiply votes

CME’s educational simulator uses a daily → hourly → five-minute sequence to move from broad context to short-horizon action. That supports role separation, but it is not evidence that those timeframes are profitable for this system. Each family/timeframe combination must remain a separately counted hypothesis. [CME chart-timeframe guide](https://www.cmegroup.com/education/courses/using-the-trading-simulator/trading-sim-in-30-seconds-chart-time-frames)

NYSE describes opening and closing auctions as concentrated liquidity and price-discovery events, and disseminates opening imbalance information as frequently as once per second when it changes. This means opening/closing setups require auction/session state and different friction assumptions from ordinary continuous trading. [NYSE opening and closing auctions](https://beta.nyse.com/publicdocs/nyse/markets/nyse/NYSE_Opening_and_Closing_Auctions_Fact_Sheet.pdf)

Implementation implication:

- Preserve the existing 5m/15m/30m/60m/daily equity ladder.
- Add explicit `asset_timeframe_policy_id` and `session_policy_id`.
- Use 1m only to refine a valid higher-timeframe setup; never count it as another confluence vote.
- Do not award repeated points when 15m/30m/60m bars were derived from the same 5m observations.
- Store the last completed-bar timestamp and aggregation anchor for every required timeframe.
- Treat each extra timeframe, threshold, or conflict rule as part of the experiment-family count.

### 4.2 Market-data freshness: age alone is insufficient

Alpaca states that its free stock feed is IEX-only, whereas SIP represents consolidated U.S.-exchange activity; Alpaca’s own example shows materially different trade counts between the feeds. Therefore an IEX observation must not be labeled market-wide volume, quote, or order flow. [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)

For options, Alpaca states that the free indicative feed contains quote derivatives rather than actual OPRA quotes and trade derivatives delayed by 15 minutes; subscribed OPRA is the consolidated best-bid-and-offer feed. Indicative data cannot support a manual execution price. [Alpaca historical option data](https://docs.alpaca.markets/us/docs/historical-option-data)

The SEC’s market-data infrastructure rule distinguishes the collection, consolidation, and dissemination of NMS quotations and transactions. Coverage and consolidation are therefore part of data quality, not just timestamp age. [SEC Market Data Infrastructure](https://www.sec.gov/rules-regulations/2020/12/market-data-infrastructure)

NIST explains that operating systems can synchronize clocks using NTP and that observed timestamp accuracy also depends on the network path. A decision audit should preserve source time, receipt time, and local clock status instead of assuming the workstation clock is exact. [NIST Internet Time Service](https://www.nist.gov/pml/time-and-frequency-division/time-distribution/internet-time-service-its)

Minimum candidate payload:

```text
feed_quality = {
  provider, feed, entitlement_status, venue_coverage,
  source_event_time, received_at, decision_at,
  age_ms, transport_latency_ms, clock_skew_ms,
  delayed, sequence_gap_count, crossed_or_invalid_quote,
  session, completed_bar_cut, last_good_at,
  freshness_threshold_ms, quality_status, blockers
}
```

This object should be computed once for the decision snapshot and reused by ranking, the UI, outcome resolution, and daily review.

### 4.3 Entry, exit, and invalidation: geometry is not execution

The SEC warns that a stop price is a trigger, not a guaranteed execution price. A stop generally becomes a market order and may fill materially away from the trigger; a stop-limit adds price control but may not execute. [SEC Investor Bulletin on stop orders](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15)

FINRA’s best-execution framework considers price, price improvement or disimprovement, likelihood of execution, speed, size, and transaction costs. A dashboard that shows only ideal candle levels omits decision-critical variables. [FINRA Rule 5310](https://www.finra.org/rules-guidance/rulebooks/finra-rules/5310)

Rule 605 reporting explicitly covers timestamps, partial executions, unexecuted orders, midpoint/spread statistics, price improvement, and relative fill rate. These are good measurement primitives for the local manual-trade journal even though this personal dashboard is not itself a Rule 605 reporting entity. [SEC Rule 605 FAQ](https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/frequently-asked-questions-rule-605-regulation-nms)

Every displayed setup should therefore freeze:

- trigger and bounded entry zone;
- maximum chase and expiration time;
- thesis invalidation and the order type assumed to express it;
- target ladder and time stop;
- decision-time bid, ask, midpoint, sizes, and quote age;
- expected fill model and cost stress;
- exact condition that changes the card to `NO_TRADE`;
- plan/model/data hashes.

Post-trade results should distinguish thesis failure from fill failure, gap-through, non-execution, partial execution, rule deviation, and ordinary loss.

### 4.4 Probability calibration: ranking score and probability are different objects

The original Brier score evaluates probability forecasts against binary outcomes. It is appropriate only when the forecast was fixed before the outcome. [Brier, 1950](https://journals.ametsoc.org/view/journals/mwre/78/1/1520-0493_1950_078_0001_vofeit_2_0_co_2.xml)

Calibration research defines a calibrated confidence as one whose predicted likelihood matches observed correctness frequency and uses reliability diagrams to expose gaps. A high classification or ranking score does not automatically satisfy that definition. [Guo et al., *On Calibration of Modern Neural Networks*](https://proceedings.mlr.press/v70/guo17a.html)

The present system correctly keeps setup score separate from probability. The remaining work is to make the qualification dimensions and fallback level visible. Recommended exact bucket key:

```text
setup_family × asset_class × instrument_group × direction ×
trigger_timeframe × session_bucket × regime × holding_horizon ×
detector_version × feed_scope × cost_model_version
```

Because exact buckets become sparse, the dashboard should show a preregistered pooling ladder, for example exact bucket → drop instrument group → drop direction → family/timeframe/regime. It must identify the level used; it must not silently substitute the overall A-grade win rate.

Display together:

- frozen forecast probability and observed event rate;
- Brier and Brier skill versus an expanding historical base-rate forecast;
- reliability plot and discrimination status;
- sample count, independent dates, confidence interval, and effective date range;
- abstention/data-block coverage;
- net-R expectancy and tail loss;
- drift status and last recalibration date.

### 4.5 False discovery and walk-forward validation: count every try

Harvey, Liu, and Zhu show that conventional significance thresholds become inadequate when many candidate factors are tried. The number of attempted rules is part of the evidence. [Harvey, Liu, and Zhu, NBER Working Paper 20592](https://www.nber.org/papers/w20592)

Bailey and colleagues show that impressive simulated results can be selected from a modest number of strategy configurations and describe probability-of-backtest-overfitting methods designed for this problem. [Bailey et al., *The Probability of Backtest Overfitting*](https://escholarship.org/uc/item/4w1110bb)

The Deflated Sharpe Ratio adjusts observed Sharpe evidence for selection bias, multiple testing, and non-normal returns. It should complement, not replace, net expectancy, drawdown, and calibration. [Bailey and López de Prado, *The Deflated Sharpe Ratio*](https://doi.org/10.3905/jpm.2014.40.5.094)

The Federal Reserve’s model-risk guidance says outcomes analysis should compare forecasts with actual outcomes at a frequency matching the forecast horizon, and that holdout analysis is not a substitute for continuing back-testing. Although written for supervised financial institutions, this is a useful validation discipline rather than a legal obligation for this personal dashboard. [Federal Reserve SR 11-7 attachment](https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107a1.pdf)

Required visible promotion evidence:

1. Frozen hypothesis and detector hash before outcomes.
2. Full family size: patterns, timeframes, directions, symbols/universes, filters, thresholds, and abandoned variants.
3. Chronological development, validation, and untouched final test periods.
4. Embargo/gap appropriate to overlapping holding horizons.
5. Point-in-time data and universe membership; revised macro inputs must use vintage data such as the St. Louis Fed’s ALFRED archive. [Federal Reserve Bank of St. Louis ALFRED](https://alfred.stlouisfed.org/help/downloaddata)
6. PBO/CSCV or another preregistered selection-overfit measure.
7. DSR or family-wise testing control.
8. Base, doubled-cost, delayed-entry, gap-through, and regime-change stress cases.
9. Independent forward-shadow period with no silent retuning.
10. Human approval for any promotion; execution authority remains unchanged.

### 4.6 Transaction costs and slippage: rank on net expectancy

FINRA’s execution-quality criteria and Rule 605’s midpoint, spread, fill-rate, price-improvement, and timestamp measures show why a constant slippage estimate is only a research fallback. [FINRA Rule 5310](https://www.finra.org/rules-guidance/rulebooks/finra-rules/5310), [SEC Rule 605 FAQ](https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/frequently-asked-questions-rule-605-regulation-nms)

The unified outcome should record:

```text
decision_mid
arrival_bid / arrival_ask / arrival_sizes
submitted_price / order_type / submitted_quantity
fill_price / fill_quantity / time_to_first_fill / time_to_complete
partial_or_unfilled_reason / cancel_or_replace_count
exit_bid / exit_ask / exit_fill
effective_spread / implementation_shortfall / fees / market impact proxy
gross_R / net_R / MFE / MAE / terminal_reason
```

For shadow outcomes, use side-aware executable assumptions: buy at ask and sell at bid, with stress variants. For real manual outcomes, retain both the frozen assumption and actual fills. A setup can remain geometrically A+ while being `NOT_TRADABLE` because post-friction reward/risk fails.

### 4.7 Options liquidity and GEX: underlying quality is necessary, not sufficient

OCC’s options disclosure document emphasizes that listed options involve substantial risks and that the quality of volatility-index inputs depends on the depth and liquidity of their underlying securities and options. [OCC Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document)

OCC also cautions that high volume can coexist with wide bid/ask spreads and recommends examining liquidity and open interest rather than treating volume alone as sufficient. [OCC on options volume and liquidity](https://www.theocc.com/newsroom/insights/2018/03-08-what-s-the-takeaway-from-the-recent-options)

Cboe’s analysis of SPX 0DTE positioning found relatively small average market-maker net gamma compared with futures liquidity and noted that market makers may hold offsetting positions in other expiries or products. This directly cautions against treating an open-interest-derived “gamma wall” as known dealer inventory or a standalone directional trigger. [Cboe 0DTE market-impact analysis](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options)

An options A+ card should require:

- an independently qualified underlying setup;
- one exact, non-expired contract or defined-risk spread;
- current OPRA NBBO, quote age, bid/ask sizes, absolute/percentage spread;
- contract volume and open interest as separate fields;
- IV and Greeks with source/model/as-of labels;
- event, early-close, settlement, and expiry risk;
- side-aware round-trip cost and a conservative fill plan;
- maximum loss and thesis invalidation tied back to the underlying.

If only Alpaca indicative options data is available, the card can teach or collect shadow evidence but must remain `RESEARCH_ONLY`.

GEX display contract:

```text
status = model_estimate
source / as_of / coverage
customer_vs_dealer_sign_assumption
buy_vs_sell_assumption
open_vs_close_assumption
spot / IV / time sensitivity
uncertainty_or_scenario_range
standalone_entry_authority = false
```

### 4.8 Daily post-trade review: review the denominator and the process

CME recommends logging the reason for a trade, targets, entry and exit, time, support/resistance, indicators, news, drawdown, and trade efficiency, followed by a daily post-mortem focused on why and how—not only P&L. [CME trade-log guidance](https://www.cmegroup.com/education/courses/building-a-trade-plan/keep-a-trade-log)

NIST’s AI Risk Management Framework recommends regular measurement of deployed-system performance, uncertainty, benchmarks, errors, and emergent risks. This is a useful governance analogy for the dashboard’s detectors and rankings. [NIST AI RMF Core, Measure](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)

One close-of-day report should reconcile:

1. Eligible universe and scan attempts.
2. Data-complete, data-blocked, and producer-failed counts.
3. A+/A/B/C/D and vetoed counts by family/timeframe/regime.
4. Every A+ lifecycle, including manual execute/reject/miss and reason codes.
5. Plan hash and what was visible at decision time.
6. Outcome at every frozen horizon, MFE, MAE, target/invalidation order, and time-stop state.
7. Planned versus actual entry/exit, rule deviations, and gross/net R.
8. False positives, false negatives, duplicates, and unmatched outcomes/fills.
9. Calibration, drift, cost-model error, and feed-quality changes.
10. Open follow-ups with owner and due date.

The daily process may append evidence and warnings. It must not silently retune pattern thresholds, timeframe roles, grade cutoffs, or cost assumptions. Those changes belong in a versioned preregistration and promotion cycle.

## 5. Recommended closure sequence

### Gate 1 — Decision-data contract (P0)

- Build the unified point-in-time feed-quality and decision-snapshot schema.
- Verify subscription/entitlement and venue coverage at startup.
- Add canonical lifecycle ID, producer aliases, `plan_hash`, and immutable first-actionable snapshot.
- Make all missing required fields fail closed.

Success: the exact card shown before a manual decision is reproducible from the audit log.

### Gate 2 — Complete denominator and daily reconciliation (P0)

- Record every eligible scan, data failure, grade, blocker, abstention, and A+ lifecycle.
- Reconcile all declared producers and cross-source duplicates.
- Join outcomes/fills explicitly; surface unmatched items.
- Replace tautological “100% reviewed” with denominator-based coverage measures.

Success: every eligible item ends in evaluated, data-blocked, or explained producer failure, and every A+ remains open until resolved.

### Gate 3 — Net execution truth (P1)

- Extend the existing fill-quality path to unfilled, cancelled, replaced, partial, and manual executions.
- Bind executable bid/ask assumptions to every shadow outcome.
- Rank on post-friction expectancy and display base/doubled-cost/delayed-entry stress.

Success: no card can be A+ trade-ready when its conservative post-friction R:R or expected value fails.

### Gate 4 — Unified calibration and promotion (P1)

- Extend bucket identity to asset/timeframe/direction/session/horizon/version/feed/cost model.
- Publish the pooling/fallback level.
- Bind experiment-family count, PBO/DSR, walk-forward results, shadow-forward evidence, calibration, and drift to one family scorecard.

Success: probability language and ranking eligibility are impossible unless the exact frozen evidence contract passes.

### Gate 5 — Asset-specific matrices and options contract gate (P1/P2)

- Freeze separate cash-equity, futures, and option-overlay matrices.
- Add futures RTH/ETH, exchange calendar, aggregation, and roll rules.
- Require current OPRA contract evidence for any options card intended for manual execution.
- Keep GEX an explicitly uncertain context estimate.

Success: no timeframe or options evidence is silently reused outside the asset/session/feed conditions under which it was tested.

### Gate 6 — End-to-end UI verification (P2)

- Show one compact manual decision card: status, why now, entry zone, max chase, invalidation, targets/time stop, post-cost R:R, timeframe alignment/conflict, feed truth, calibrated evidence, blockers, and `STAND_ASIDE` reason.
- Show a source-health strip and an explicit “data incomplete” state instead of empty success.
- Verify desktop/mobile rendering and stale/degraded/missing/error states with deterministic fixtures.

Success: a user can answer “why this setup, why now, where wrong, what is the cost, how certain is the evidence, and what blocks it?” without switching pages.

## 6. Non-negotiable implementation guardrails

- Keep `execution_enabled=false` and `can_submit_orders=false` on all new fields and outputs.
- Do not change broker credentials, bot bodies, signal-registry authority, or order routes.
- Do not convert grades or social claims into probabilities.
- Do not relabel IEX as consolidated SIP, indicative options as OPRA, OHLCV proxies as order flow, or open-interest heuristics as known dealer inventory.
- Use completed bars and point-in-time inputs only; preserve session/aggregation rules.
- Preserve all tested variants, rejections, abstentions, and failures.
- Keep daily outcome collection separate from model retuning.
- Continue deterministic replay, source provenance, freshness labels, and fail-closed behavior.

## 7. Primary sources

1. [Alpaca Market Data FAQ — IEX versus SIP](https://docs.alpaca.markets/us/docs/market-data-faq)
2. [Alpaca Historical Option Data — indicative versus OPRA](https://docs.alpaca.markets/us/docs/historical-option-data)
3. [SEC Market Data Infrastructure](https://www.sec.gov/rules-regulations/2020/12/market-data-infrastructure)
4. [NIST Internet Time Service](https://www.nist.gov/pml/time-and-frequency-division/time-distribution/internet-time-service-its)
5. [NYSE Opening and Closing Auctions Fact Sheet](https://beta.nyse.com/publicdocs/nyse/markets/nyse/NYSE_Opening_and_Closing_Auctions_Fact_Sheet.pdf)
6. [CME Chart Time Frames](https://www.cmegroup.com/education/courses/using-the-trading-simulator/trading-sim-in-30-seconds-chart-time-frames)
7. [SEC Investor Bulletin — stop, stop-limit, and trailing-stop orders](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15)
8. [FINRA Rule 5310 — Best Execution and Interpositioning](https://www.finra.org/rules-guidance/rulebooks/finra-rules/5310)
9. [SEC Rule 605 FAQ](https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/frequently-asked-questions-rule-605-regulation-nms)
10. [Brier, *Verification of Forecasts Expressed in Terms of Probability*](https://journals.ametsoc.org/view/journals/mwre/78/1/1520-0493_1950_078_0001_vofeit_2_0_co_2.xml)
11. [Guo et al., *On Calibration of Modern Neural Networks*](https://proceedings.mlr.press/v70/guo17a.html)
12. [Harvey, Liu, and Zhu, *… and the Cross-Section of Expected Returns*](https://www.nber.org/papers/w20592)
13. [Bailey et al., *The Probability of Backtest Overfitting*](https://escholarship.org/uc/item/4w1110bb)
14. [Bailey and López de Prado, *The Deflated Sharpe Ratio*](https://doi.org/10.3905/jpm.2014.40.5.094)
15. [Federal Reserve SR 11-7 — Model Risk Management](https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107a1.pdf)
16. [Federal Reserve Bank of St. Louis ALFRED](https://alfred.stlouisfed.org/help/downloaddata)
17. [OCC Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document)
18. [OCC — options volume, open interest, spreads, and liquidity](https://www.theocc.com/newsroom/insights/2018/03-08-what-s-the-takeaway-from-the-recent-options)
19. [Cboe — SPX 0DTE positioning and market impact](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options)
20. [CME — Keep a Trade Log and Daily Post-Mortem](https://www.cmegroup.com/education/courses/building-a-trade-plan/keep-a-trade-log)
21. [NIST AI RMF Core — Measure](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)

