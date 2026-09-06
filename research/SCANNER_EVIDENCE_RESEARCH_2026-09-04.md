# Scanner evidence research — 2026-09-04

Scope: primary-source research for a shadow-only scanner. This note does not establish a profitable strategy, inspect account entitlements, authorize purchases, or change execution authority. Recommendations below are engineering hypotheses unless explicitly identified as documented facts.

## Documented feed facts

Alpaca distinguishes IEX, a single exchange, from consolidated SIP data. Its FAQ says latest SIP endpoints require a subscription; historical SIP queries without that subscription require `end` to be at least 15 minutes old. Feed defaults depend on entitlement. Therefore an explicit historical `feed=sip` request can be useful for completed-session research without proving live SIP permission. Authentication or entitlement failures must remain failures, not silent feed changes. Record requested and returned feed separately. [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)

Recommended experiment: compare identical completed sessions and symbols using separately labeled IEX and SIP bars. Measure missing minutes, OHLC disagreements, setup triggers and invalidation differences. This isolates feed effects from strategy effects. Do not assume a repaired SIP historical replay was tradable using the live IEX observations available then. Keep an as-observed result and a consolidated-reference result.

Stock quotes do not establish an option's executable price. Alpaca's historical options documentation describes indicative quotes as modified derivatives, not actual OPRA quotes; indicative trades are delayed 15 minutes. OPRA supplies consolidated options BBO and requires subscription. Therefore any option-return score needs the actual contract, expiry, strike, call/put, timestamped contract quotes and verified feed—not an underlying percentage move or a social-media gain. Missing contract data means option outcome unavailable. [Alpaca Historical Option Data](https://docs.alpaca.markets/us/docs/historical-option-data)

Alpaca recommends streaming over polling for up-to-date options pricing and documents authentication rejection for unauthorized streams. A bounded streaming prototype is a latency hypothesis, not evidence that additional intelligence predicts better trades. Benchmark event-to-detection and detection-to-Discord separately before replacing the existing path. [Alpaca Real-time Option Data](https://docs.alpaca.markets/us/docs/real-time-option-data)

## Evaluation design

Repeated strategy selection on the same history creates false positives. Bailey et al. show why ordinary holdout testing can be unreliable when researchers repeatedly select configurations, and develop a probability-of-backtest-overfitting framework. Consequently, a profitable replay of the screenshots' day is discovery evidence only. [Original PBO paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)

Recommended protocol:

1. Freeze a versioned baseline and a small, predeclared challenger set. Log every attempted variant, including unsuccessful ones.
2. Use chronological sessions: choose parameters on earlier sessions, freeze them, then evaluate later untouched sessions. Exclude training outcomes whose observation horizon overlaps the evaluation period. Never tune using the evaluation results and continue calling that period untouched.
3. Replay all nominated opportunities, not just delivered winners. Store candidate, rejection reason, feed, data availability and policy version. Count one plan once; compare baseline/challenger on the same opportunity set.
4. Report both delivered-alert precision and missed-opportunity coverage. Rejected candidates need their own timestamped hypothetical evaluation, not fabricated Discord receipts. Separate research outcomes from delivery-qualified calibration.
5. Group uncertainty by session because same-day symbols and repeated alerts are dependent. Report sample size, sessions, net expectancy, adverse excursion, drawdown, coverage and latency percentiles. Three to five sessions can test plumbing; they cannot certify optimal settings.
6. Keep any promotion a human-reviewed nomination. Sparse samples or unavailable costs remain insufficient evidence.

The Deflated Sharpe Ratio addresses multiple-selection and non-normal-return inflation; it does not rescue absent data. Preserve the trial ledger now so later statistical analysis can account for the search performed. Do not advertise a maximum backtest Sharpe as strategy quality. [Original DSR paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)

## Execution-cost and chart comparison requirements

The SEC explains that execution takes time, prices can move, and quoted size limits availability. Therefore a chart touch is not a confirmed fill. [SEC Trade Execution](https://www.sec.gov/about/reports-publications/investorpubstradexec)

Recommended shadow scoring uses side-appropriate bid/ask observations after actual delivery acknowledgement, additional user-response-delay scenarios, fees and explicit slippage scenarios. Never use favorable within-bar sequencing: if both stop and target occur in one unresolved bar, mark ambiguity or use a disclosed conservative policy. Keep stock directional R separate from option P&L. Validate TradingView comparisons by matching instrument, exchange/feed, timezone, session and adjustment settings; screenshots alone cannot establish intrabar order or fill quality.

Priority: obtain honest historical/reference coverage and an immutable candidate ledger first; compare frozen settings second; consider lower-latency streaming after stage timings identify the bottleneck. No source here establishes that more indicators, another model, stricter filters, or a paid feed alone improves net returns.
