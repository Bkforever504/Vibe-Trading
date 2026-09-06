# Social Methods: Regime, Liquidity, and AI-Scanner Evaluation

**Date:** 2026-09-03  
**Scope:** evidence review and repository gap assessment; no production changes  
**Decision:** retain every social claim as a lead. Only a causal regime challenger and objectively defined sweep/reclaim events merit new shadow research. Nothing in the screenshots supports execution or a calibrated win probability.

## Executive decision

| Claim | Testable core | Evidence verdict | Vibe-Trading status | Action |
|---|---|---|---|---|
| Six-agent regime-aware HMM/Markov stack | infer persistent latent return/volatility states and route already-defined strategies by state | Established modeling family; trading value is conditional and must be demonstrated out of sample | Partial. A daily `hmm_regime_scanner.py` exists, but it is a deterministic threshold classifier, **not a fitted HMM**; its displayed “probabilities” are recent label frequencies, not filtered state posteriors | Build a separate shadow challenger with causal filtered probabilities, entropy/confidence, frozen rolling fits, transition persistence, and a no-regime baseline |
| HTF level sweep → MSS → FVG/IFVG retest | completed-bar breach/reclaim of a pre-existing level, followed by quantified displacement/structure and retest | Stop clustering and price cascades have microstructure support; ICT labels do not establish profitability | Already specified and tested. The MES sequence failed out of sample and is `execution_enabled=false` | Keep visible as research evidence; do not promote or retune on the same holdout |
| OTE 0.62–0.79 | retracement-depth band | No credible evidence that this band is privileged | Fibonacci-confluence research exists; no reason to hard-code OTE | If tested, compare prospectively with matched 0.38–0.50, 0.50–0.62, and random bands |
| “Range trap” | stable range → boundary breach → close back inside within N bars → midpoint/opposite edge outcome | Plausible, measurable false-breakout family; “insider” intent is unobserved | Mostly covered by failed-breakout/range families and liquidity-sweep work | Add only as an isolated shadow cohort if its predicate is materially distinct; test reversal and continuation symmetrically |
| TempoICT 177 trades / 76.84% win rate | one-hour/four-hour liquidity sweep + IFVG in NY morning | Screenshot is an aggregate table, not a reproducible ledger | No verified source ledger | Do not import the percentage. Require all 177 timestamps, instruments, entry/exit rules, costs, rejected signals, and parameter history |
| Aristotle “5/5” | DELL/HOOD/WMT/TSLA options calls | One selected day and percentage returns | Social intake can record the post, but no contemporaneous complete ledger is present | Discovery lead only; reconstruct only from timestamped alerts and NBBO-at-alert evidence |
| BOA 77–78% “odds” alerts | direction plus target-price quantiles | No model, calibration set, denominator, or outcome ledger shown | No calibrated BOA source | Treat “odds” as an unverified label. Never display them as probabilities without reliability/Brier calibration |
| “Grok/AI scans everything in real time” | broad universe ranking plus deterministic confirmation | AI can triage candidates; it does not create market data, fills, or edge | Vibe already has deterministic scanners, social intake, governed evidence cards, lifecycle, reconciliation, and rule updates | Use AI only to extract/normalize leads. Market data and rule evaluation must remain deterministic and timestamped |

## What the primary evidence actually supports

### 1. Regime models are legitimate context models, not automatic alpha

Markov-switching models allow parameters such as means and volatility to change with an unobserved state. The academic literature documents regime variation in return distributions and correlations and discusses allocation implications; it does not imply that a chosen three-state intraday system will be profitable. [Ang and Timmermann, NBER Working Paper 17182](https://www.nber.org/papers/w17182) Ang and Bekaert find some out-of-sample allocation value, especially for cash/bond/equity allocation, while warning that gains are less clear within an all-equity portfolio. [NBER Working Paper 10080](https://www.nber.org/papers/w10080)

Regime results are particularly vulnerable to mistaken interpretation: infrequent structural changes can be statistically confused with long memory. [Diebold and Inoue, NBER Technical Working Paper 264](https://www.nber.org/papers/t0264) A standard implementation should therefore expose fitted transition probabilities, filtered state probabilities, model diagnostics, and uncertainty; Statsmodels documents a first-order `k`-regime Markov-switching regression suitable as a transparent benchmark. [Statsmodels `MarkovRegression`](https://www.statsmodels.org/dev/generated/statsmodels.tsa.regime_switching.markov_regression.MarkovRegression.html)

**Repository finding.** `scripts/hmm_regime_scanner.py` calls itself “HMM-style,” but `classify_observation()` assigns states by fixed z-score thresholds. `state_probabilities()` then counts assigned labels over the last 20 observations. No emission distribution, likelihood maximization, forward filter, or latent posterior is fitted. This is a useful deterministic regime heuristic, but the dashboard must not imply it is an HMM posterior.

**Admissible challenger.** Fit a small daily model using only data available through the prior completed session; use filtered rather than full-sample smoothed probabilities; freeze state count, features, initialization policy, and refit schedule; report posterior entropy and `unknown` when confidence is weak; benchmark incremental performance against the current heuristic and a simple realized-volatility filter. It may modify a shadow evidence card or risk posture only after prospective validation. It may not create a candidate by itself.

### 2. Stops cluster, but “insiders hunted your stop” is not observable

New York Fed research using an actual dealer order book found stop-loss and take-profit orders clustering at round numbers, with unusually rapid/extended moves around clustered stops. That supports a testable stop-cascade mechanism, not a claim that an identifiable insider deliberately targeted a retail account. [Osler, NY Fed Staff Report 150](https://www.newyorkfed.org/research/staff_reports/sr150.html) Related NY Fed work found some predictive content in published support/resistance levels and explained both bounces and acceleration through order clustering; the evidence is foreign exchange and cannot simply be assumed for every U.S. equity or futures contract. [NY Fed Staff Report 125](https://www.newyorkfed.org/research/staff_reports/sr125.html)

For U.S. equities, short-horizon price changes have a documented relationship with top-of-book order-flow imbalance and available depth. That supports using verified quote/order-book features when available; OHLCV cannot be relabeled as institutional order flow. [Cont, Kukanov and Stoikov](https://arxiv.org/abs/1011.6402)

The honest feature name is `liquidity_sweep_reclaim`, not “insider entry.” A causal record must include: level origin and availability time; breach distance in ticks/ATR; completed-bar reclaim deadline; displacement; volume or verified OFI; invalidation; outcome horizon; and whether price instead continued through the level.

### 3. FVG/IFVG and OTE remain hypotheses

A recent non-peer-reviewed study of roughly 40,000 futures FVG observations reports a descriptive reaction but no tradable edge after honest construction and costs; an attractive hourly result disappeared when exits were resolved with one-minute paths. It is provisional evidence, but exactly illustrates why completed-bar timestamps and lower-timeframe path resolution matter. [Barot, SSRN 7148099](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7148099)

A peer-reviewed study across major equity indices found Fibonacci-zone bounce rates statistically indistinguishable from non-Fibonacci zones. This directly argues against treating the screenshot's 0.62–0.79 OTE interval as special without a controlled test. [Expert Systems with Applications, DOI 10.1016/j.eswa.2021.115893](https://www.sciencedirect.com/science/article/pii/S0957417421012495)

**Repository result is stronger than the screenshots.** The frozen MES liquidity-sweep → MSS/FVG → retest proxy produced 19 development trades at +$20.02 expectancy, but then 2 selection trades at -$61.86 and 6 final trades at -$36.85; doubled friction was also negative and every promotion gate failed. `data/liquidity_sweep_mss_retest_results.json` correctly labels it `rejected_out_of_sample`. The broader global social tournament likewise found the sweep/MSS/FVG family negative on SPY, QQQ, and MES after friction. This is evidence against promotion, not an invitation to optimize the failed holdouts.

## Social performance claims

### TempoICT: 177 trades, 76.84% wins

The screenshot shows a spreadsheet summary with `Total Trades: 177`, `Win %: 76.84%`, median two-minute time to first profit, and additional target statistics. It does not show the 177-row trade ledger, instruments/dates, signal timestamp, entry price, exit policy, fees, slippage, rejected setups, overlapping trades, or whether parameters changed after seeing results. Consequently:

- the claimed win rate cannot be reproduced or audited;
- the denominator and win definition are unknown;
- a high win rate says nothing about expectancy without average win/loss and tail loss;
- the 41.24% “chase entry” figure illustrates that rule interpretation may be discretionary.

Status: **unverified marketing evidence**. The rule text is eligible for preregistered replication, but the 76.84% number is not eligible for any dashboard probability field.

### Aristotle Investments: “5/5 direct signals”

The screenshot lists DELL 267%, HOOD 50%, WMT 60%, WMT 47%, and TSLA 20% for one day. It does not disclose contracts, alert timestamps, entry quotes, exits, losing days, sizing, spread/slippage, or the complete signal population. It is selected-outcome evidence and cannot establish a 100% win rate or expected return.

Status: **discovery lead only**. Admission requires contemporaneous callout capture with symbol, direction, contract/underlying, entry zone, invalidation, target, timeframe, publication time, and NBBO-at-alert when options are involved.

### BOA “77%/78% odds”

The screenshot provides NQ direction, an entry reference, target levels labeled 50/70/90%, and a future grading time. It provides no definition of those probabilities, training/holdout periods, calibration bins, Brier/log score, sample size, or complete forecast archive. A 90% target label is therefore not a calibrated 90% probability.

Status: **unverified probability claim**. If enough point-in-time forecasts are collected, score each target as a horizon-specific binary event, preserve every forecast, and publish reliability bins, Brier score, coverage, and maximum adverse excursion. Until then the dashboard should render `vendor_claim_unverified`, never “78% odds.”

### AI/Grok scanner

The post claims that Grok scans in real time, AI analyzes price action, identifies high-probability setups, and waits for confirmation, alongside a selected profit image. There is no data-source specification, candidate rule, latency measurement, full trade ledger, or evidence that the screenshot resulted from the described process.

Status: **architecture slogan, not a strategy**. Vibe-Trading already has the useful separation: social discovery → deterministic candidate → independent evidence cards → veto/risk gate → shadow alert → simulated lifecycle → reconciled outcome → rule update. An LLM may extract a proposed rule or summarize evidence, but it must not manufacture market observations, odds, fills, or stops.

## Repository coverage and genuine gaps

### Already present

- `scripts/hmm_regime_scanner.py`: daily SPY/QQQ/IWM deterministic regime heuristic and transition counts.
- `research/liquidity_sweep_mss_retest_lab.py` plus frozen spec/results: causal sweep/MSS/FVG replication with costs and chronological development/selection/final periods.
- `research/breakaway_fvg_structure_lab.py`: separate FVG/structure experiment; the literal conjunction was too rare and negative after costs.
- `scripts/liquidity_sweep_scanner.py`: read-only level/sweep discovery.
- `scripts/institutional_confluence_shadow.py`: fail-honest independent-evidence availability and repeated completed-bar confirmation; it explicitly refuses to infer unavailable dark-pool, NBBO flow, vanna, or dealer positioning.
- `research/aplus_timeframe_matrix.json`: explicit trigger, confirmation, structure, regime, and advisory timeframe roles.
- Existing failed-breakout reversal and range-mean-reversion families, social intake, governed decisions, alert lifecycle, reconciliation, and continuous-improvement reporting.

### Genuine gaps worth addressing

1. **Naming/semantics:** label the current output `heuristic_regime_frequency`; do not present it as a true HMM posterior.
2. **True regime challenger:** separate script and ledger for causal filtered probabilities, entropy, fit diagnostics, transition persistence, and baseline comparison. Keep it shadow-only.
3. **Symmetric level outcome:** every sweep candidate should score both reclaim/reversal and stop-cascade/continuation. This prevents hindsight from defining every failed breakout as a successful “trap.”
4. **Vendor forecast calibration lane:** preserve point-in-time BOA-like forecast cards and score calibration separately from trade P/L. Missing predictions must remain in the denominator.
5. **Social completeness score:** a winning screenshot without entry timestamp, geometry, full ledger, and executable quote should remain visible as a research lead but must have zero influence on execution or probability.

## Frozen test proposals

### A. Regime posterior challenger

- Universe: SPY, QQQ, IWM daily completed bars.
- Inputs: prior-session return, realized volatility, range/ATR, and cross-index dispersion; no same-day future information.
- Compare: current deterministic heuristic, simple volatility terciles, and 2/3-state Markov-switching models.
- Outputs: filtered posterior, entropy, transition matrix, fit failure, and `unknown` state.
- Evaluation: prospective log loss/state stability plus incremental cost-adjusted expectancy of existing candidate families by frozen regime. No model is retained merely because its state labels explain past charts.

### B. Range sweep tournament

- Define the range before the test window using completed bars.
- Require a boundary breach by a frozen tick/ATR amount.
- Classify only after either a completed-bar reclaim within `N` bars or continuation by a separate threshold.
- Compare reversal entry, continuation entry, and no-trade; resolve ambiguous stop/target bars with lower-timeframe paths; apply spread, fees, slippage, and delayed-alert stress.
- Report by instrument, direction, time bucket, volatility regime, and level type. Freeze selection/final holdouts.

### C. OTE controlled experiment

- Anchor the impulse with a deterministic, pre-existing swing rule.
- Compare 0.62–0.79 against matched retracement bands and randomized zones.
- Keep FVG present/absent as a factorial feature rather than silently requiring it.
- One hypothesis family, declared search count, walk-forward evaluation, and multiple-testing control.

## Final recommendation

Implement no screenshot percentage and no “insider” narrative. The best actionable lesson is not a new indicator; it is a stricter experiment:

1. Preserve regime context, but distinguish the current heuristic from a real latent-state posterior.
2. Keep liquidity sweep/reclaim and range traps visible in shadow alerts with exact timestamps and geometry.
3. Score reversal and continuation symmetrically.
4. Keep FVG/IFVG and OTE as contextual research features only.
5. Demand complete ledgers and probability calibration before importing any TempoICT, Aristotle, BOA, or AI-scanner performance claim.

The SEC explicitly warns that social posts may be inaccurate, incomplete, or misleading and that investors should not decide solely from them. That is the correct evidence policy for all screenshots reviewed here. [SEC/Investor.gov social-media stock-tip alert](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/social-media-stock-scams)
