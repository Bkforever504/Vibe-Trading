# Market Structure Decision System

Status: preregistered read-only research layer  
Authority: manual review only  
Execution: `execution_enabled=false`, `can_submit_orders=false`

## Objective

Recognize objective, causal market structures from completed bars; distinguish a valid setup from its dangerous look-alike; and return one of four decisions:

- `READY_TO_REVIEW`: the pattern, trigger, location, market-quality, and timing gates pass.
- `WAIT`: a plausible setup exists, but confirmation or a quality gate is incomplete.
- `REJECT`: a hard veto is active, including a failed breakout, stale quote, wide spread, or higher-timeframe conflict.
- `STAND_ASIDE`: no objectively defined setup is present or there is insufficient data.

The system does not promise perfect prediction. “Timing” means the earliest causal completed-bar confirmation for a preregistered rule, with no repainting and no hindsight pivot placement. Scores are quality ranks, not win probabilities.

## Research foundation

The rule design follows these evidence constraints:

1. Chart patterns must be converted from subjective pictures into reproducible algorithms. Lo, Mamaysky, and Wang found that several algorithmically recognized patterns contained incremental information, while emphasizing that ordinary visual charting is subjective: [NBER Working Paper 7613](https://www.nber.org/papers/w7613).
2. Simple moving-average and trading-range-break rules have historical evidence, but that evidence cannot be treated as a timeless guarantee: [Brock, Lakonishok, and LeBaron, Journal of Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1992.tb04681.x).
3. Trying many rules and keeping the winners creates data-snooping bias. All thresholds below are frozen before forward evaluation, following the warning in [Sullivan, Timmermann, and White](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00163).
4. Price and volume jointly contain information not present in price alone, supporting participation confirmation rather than naked shape recognition: [Blume, Easley, and O’Hara](https://volume.technicalanalysis.org.uk/BlEO94.pdf).
5. Local highs/lows and round-number areas can behave as support/resistance, while a break and a bounce are different events. This supports separate rejection, breakout, retest, and failure states: [Federal Reserve Bank of New York](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf).
6. Head-and-shoulders has been evaluated with algorithmic recognition rather than visual labeling, but remains one conditional feature—not standalone authority: [Savin, Weller, and Zvingelis](https://academic.oup.com/jfec/article-abstract/5/2/243/785044).
7. Small trading costs can create economically meaningful no-trade regions, which is why spread, liquidity, and post-friction geometry are entry gates: [Lo, Mamaysky, and Wang](https://www.nber.org/papers/w8311). Wide spreads and high volatility also reduce expected market depth: [Engle and Lange](https://www.nber.org/papers/w6129).
8. A stop price is not a guaranteed execution price. The dashboard therefore shows structural invalidation, not an execution promise, consistent with [FINRA’s stop-order guidance](https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets) and [order-type guide](https://www.finra.org/investors/investing/investment-products/stocks/order-types).

## Causal data contract

- Primary trigger frame: completed 5-minute OHLCV bars.
- Context frames: completed 15-minute and 60-minute bars when supplied; otherwise causally resampled completed bars.
- Quote: latest bid, ask, timestamp, age, and spread.
- Optional context: time-of-day RVOL, average dollar volume, catalyst, benchmark return, and sector return.
- Confirmed swing: a pivot with two completed bars on both its left and right. A pivot at position `i` becomes visible only at `i + 2`.
- No forming-bar trigger, centered indicator, future extrema, retroactive label, or image-only pattern may create a decision.
- Every output carries source labels, freshness, `closed_bar_only=true`, and false execution flags.

## Pattern ladder: simplest to most complex

| Pattern | Complexity | What it must look like | Entry confirmation | Invalidation | Primary exit |
|---|---|---|---|---|---|
| Trend pullback | Simple | Directional slope, controlled retracement to the short trend mean | Completed bar resumes in trend direction | Beyond pullback extreme / trend mean buffer | 1R, 2R, then confirmed-swing trail |
| Support/resistance rejection | Simple | Price tests a confirmed swing level and closes away from it | Rejection-bar extreme breaks | Beyond rejected level | Opposite range boundary or 2R |
| Range break and retest | Simple | Eight-bar base, close outside level, retest of old boundary, close back with break | High/low of the confirming hold bar | Beyond retest extreme | 1R and 2R |
| VWAP reclaim/reject | Simple | Prior close on one side, completed bar crosses and closes directionally on the other | Reclaim/rejection-bar extreme | VWAP plus ATR buffer | 1R and 2R |
| Double top/bottom | Intermediate | Two confirmed extrema within `max(0.55 ATR, 0.30%)` with an intervening neckline | Completed neckline close | Beyond the two extrema | Pattern risk at 1R and 2R |
| Head-and-shoulders / inverse | Intermediate | Three confirmed extrema; shoulders match within tolerance; head exceeds shoulders by `0.35 ATR` | Completed neckline close | Beyond right shoulder | 1R and 2R |
| Compression breakout | Intermediate | Median range contracts to at most 72% of the prior range; expansion closes outside with at least 1.25x local volume | Expansion-bar extreme | Opposite compression boundary | 1R and 2R |
| Flag continuation | Intermediate | At least `2 ATR` impulse, countertrend retracement no deeper than 55%, completed resumption close | Resumption-bar extreme | Beyond flag extreme | 1R, 2R, swing trail |
| Liquidity sweep + structure shift + retest | Advanced | Price exceeds a five-bar extreme, reclaims it, displaces through local structure, then holds | Hold-bar extreme | Beyond sweep extreme | 1R and 2R |
| ICT CISD universal sequence | Advanced | Interacted HTF FVG, tracked third-candle range, liquidity sweep, chronological IFVG inversion, then candle-body CISD close | Opposing delivery-leg open after the completed body close; wick-only remains pending | Beyond sweep extreme | 1R and 2R until local outcomes justify structural targets |
| Multi-timeframe alignment | Advanced confirmation | Available non-neutral 5m/15m/60m trends agree with setup direction | It confirms another setup; never creates one alone | Conflict is a hard blocker | Use underlying setup exits |

The detector also calculates session VWAP, ATR, linear trend strength, confirmed swings, directional efficiency, range location, volume expansion, and quote quality. These are observable inputs; none is presented as a causal economic law or standalone edge.

### CISD universal-sequence contract

`ict_cisd_sequence_v1` is an independent completed-OHLC implementation of the public model description; it does not copy or claim parity with the protected TradingView source. The observable state machine is frozen as:

1. detect a completed three-candle HTF FVG and require execution-frame price interaction;
2. retain the high/low of the FVG's third candle;
3. require a sweep and reclaim of a prior five-bar extreme;
4. require a pre-existing opposite FVG to invert after that sweep;
5. confirm CISD only on a completed body close through the opposing delivery leg's open.

Supported context mappings are 15m→1m, 30m→3m, 1h/60m→5m, and 4h→15m. The dashboard displays all five stages, the mapped execution frame, displacement and SMT availability, and `PENDING` versus `CONFIRMED`. SMT remains unavailable unless correlated completed bars are explicitly supplied. Displacement is a bonus; it cannot fill a missing core stage. Future bars cannot retroactively improve a confirmed sequence.

For the live stock dashboard, 60-minute context is assembled from completed Alpaca 30-minute bars anchored at 09:30 ET. Only 09:30–16:00 ET bars are admitted, preventing premarket and after-hours buckets from contaminating RTH FVG structure.

The detector starts with `probability_status=unvalidated_pattern_hypothesis` and no research prior. It cannot enter the probability-first ranking lane until its own strictly prior outcomes satisfy the same 100-observation, 30-date, conservative-bound, positive-Brier-skill contract.

## Worst setups and anti-pattern vetoes

| Anti-pattern | Objective recognition | Decision effect |
|---|---|---|
| Failed breakout trap | Breaks an eight-bar boundary, then closes back through it beyond tolerance | `REJECT` when it opposes the proposed direction |
| Late chase / exhaustion | Price is at least 2.25 ATR from its short mean, or at least 1.75 ATR after three same-direction closes | Location score collapses; display as worst look-alike |
| Midrange chop | Directional efficiency below 0.25 while price sits in the middle 36% of the recent range | Strong penalty; normally `WAIT` or `STAND_ASIDE` |
| Broadening instability | Recent average bar range exceeds the prior average by 55% while directional efficiency is below 0.45 | Penalty and no aggressive entry |
| Weak breakout participation | Breakout volume is below 1.20x the base median | Pattern remains weak / waiting |
| Wide spread or stale quote | Spread missing or above 35 bps; quote older than the live/recent boundary | Hard `REJECT` |
| Higher-timeframe conflict | Any available directional higher frame opposes the proposed direction | Hard `WAIT`/`REJECT` |
| Low RVOL | Time-of-day RVOL below 1.25 when available | Hard quality blocker |
| Low dollar liquidity | Average dollar volume below $20 million when available | Hard quality blocker |

## Canonical grading model

Detector, API, watchlist, and dashboard now use the same `pattern_grade_v1` score. There is no second candidate grade:

| Factor | Weight | Meaning |
|---|---:|---|
| Pattern base evidence | 25% | Locally validated base rate when available; otherwise a visibly labeled research or neutral prior |
| Volume / RVOL | 15% | Completed-bar participation confirmation |
| Multi-timeframe alignment | 20% | Agreement across available completed-bar frames |
| Regime fit | 15% | Fit to the observable price-trend regime; unavailable HMM/GEX inputs are not invented |
| Cross-family confluence | 15% | 25 points per distinct confirmed detector family, capped at 100 |
| Planned reward:risk | 10% | Objective trigger-to-invalidation geometry and targets |

The weighted score is then multiplied by disclosed penalties: anti-pattern `×0.5`, macro window `×0.6`, wide spread `×0.7`, and stale feed `×0.5`. Grades are `A` (85+), `B` (70–84.99), `C` (55–69.99), and `D` below 55.

`A / ALL_OBSERVED_CONDITIONS_ALIGNED` requires strong volume, timeframe, regime, and reward:risk components with no active penalty. A confirmed chart shape by itself normally remains `B / WAIT`; this is intentional. `validation_status` separately says whether the base evidence is locally forward-validated, a research prior, or uncalibrated. A grade is never a probability, expected return, size instruction, or promise that the trade will win.

## Probability-first dashboard ranking

The cockpit schema-v8 ranking policy always prefers the highest defensible conditional probability among setups that are timely, confirmed, unblocked, and manually reviewable. A candidate may enter that probability-first lane only when all of these are present:

- locally forward-calibrated or calibrated-holdout status;
- at least 100 resolved observations;
- at least 30 independent trading dates;
- a supplied conservative probability lower bound;
- positive Brier skill versus an expanding historical base-rate forecast.

Qualified candidates rank by conservative lower bound first, then decision quality. A larger unqualified percentage cannot outrank a qualified one. Historical win rates remain references and never qualify as live conditional probabilities. When no current candidate clears the calibration contract, the dashboard explicitly switches to `decision_quality_fallback_no_qualified_probability`; it still shows the best observable setup, but it does not invent a percentage.

## Entry and exit state machine

```text
completed bars + fresh quote
        |
        v
recognize positive patterns and anti-patterns
        |
        +-- no objective setup --------------------------> STAND_ASIDE
        +-- stale/wide/failed/conflicting ---------------> REJECT
        +-- shape exists but trigger/retest incomplete --> WAIT
        +-- confirmed A grade + no blocker -------------> READY_TO_REVIEW
```

For a valid manual-review setup:

- Trigger: the confirming bar’s directional extreme or the objective neckline/level.
- Entry zone: trigger ± the smaller of `0.12 ATR` and `0.15R`.
- Invalidation: structural failure level. It must never be widened after entry.
- Target 1: +1R from the trigger.
- Target 2: +2R from the trigger.
- Time stop: six completed 5-minute bars without progress.
- Management: at +1R, reduce risk or trail behind the last confirmed swing. The UI describes this; it cannot submit or modify orders.

## Forward validation before trusting rankings

The recognizer is deployed as an observation and grading layer, not a promoted strategy. Each pattern must pass all of the following before its score can be interpreted as evidence of edge:

1. Freeze pattern definitions, thresholds, universe, market hours, feed, and cost assumptions.
2. Log decision-time snapshots and outcomes without rewriting history.
3. Evaluate MFE, MAE, 1R-before-invalidation, 2R-before-invalidation, time-to-trigger, slippage, and missed-trade rate.
4. Use chronological walk-forward splits and strictly future outcomes.
5. Require at least 100 completed occurrences, 30 independent dates, and multiple market regimes for a pattern-level estimate.
6. Report gross and post-cost results separately; segment by spread, liquidity, RVOL, time bucket, catalyst state, direction, and market regime.
7. Correct for multiple testing / data-snooping before changing thresholds.
8. Keep disappointing and rejected patterns in the report. Do not delete them from the denominator.
9. Promote only through the existing preregistration and human-approval path. This module cannot promote itself or grant execution authority.

## Implementation map

- Detector and catalog: `scripts/market_structure_intelligence.py`
- Canonical scoring function: `agent/src/tools/pattern_grade_scorer.py`
- Preregistered 16-pattern research inventory: `research/pattern_taxonomy.json`
- Live integration: `scripts/live_opportunity_engine.py`
- Dashboard types: `frontend/src/lib/api.ts`
- Dashboard surface: `frontend/src/components/trading/LiveOpportunityPanel.tsx`
- Causal/unit tests: `agent/tests/test_market_structure_intelligence.py`
- Engine contract tests: `agent/tests/test_live_opportunity_engine.py`

## Known limitations

- IEX data is not the full consolidated tape; quote and bar provenance must remain visible.
- Five-minute OHLCV cannot reveal queue position, hidden liquidity, or the intrabar ordering of high and low.
- Pattern geometry can fail abruptly on news, halts, gaps, and volatility shocks.
- A structural invalidation is not a guaranteed fill price.
- The initial catalog is heuristic and preregistered. It must earn credibility through forward, post-cost evidence; visual plausibility is not validation.
