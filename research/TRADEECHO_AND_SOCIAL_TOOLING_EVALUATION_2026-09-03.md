# TradeEcho and Social Tooling Evaluation — Governed Shadow Decision Spine

**Research date:** 2026-09-03  
**Scope:** TradeEcho, the Fable Orchestrator repository shown in the supplied screenshots, OpenMarket's Price Action / Trend Signals / Oscillator toolkits, and the proposed use of GEX/VEX as LLM confluence.  
**Required operating spine:** `candidate → independent evidence cards → veto/risk gate → shadow alert → simulated lifecycle → reconciled outcome → rule update`

## Executive decision

| Item | Decision | Reason |
|---|---|---|
| TradeEcho platform | **Do not integrate or scrape. Defer purchase.** A short, manual, terms-compliant shadow evaluation is reasonable if desired. | Useful first-party methodology and workflow ideas, but proprietary SaaS, broker/execution surface, public terms restricting scraping, material modeling assumptions, and no independent audit of the published performance claims. |
| Fable Orchestrator | **Do not install in the trading repository.** Reuse only its process ideas. | MIT-licensed, but extremely new and lightly adopted; one lane deliberately bypasses permissions and its own documentation says the deny list is not confinement. The viral claims of “free,” “unlimited,” and GPT-5.6 Luna on every task do not match the repository requirements or current routing. |
| OpenMarket toolkits | **Do not copy or import source.** Independently reimplement only narrowly selected mechanics after preregistration and forward shadow testing. | Source-visible is not the same as open source. The scripts contain no explicit license, the author is unverified, the scripts were one day old at review time, and no auditable out-of-sample evidence was available. |
| GEX/VEX confluence | **Adopt only as one optional, correlated dealer-positioning context card.** | GEX and VEX normally share the same option-chain inputs and inventory assumptions, so they are not independent votes. Unknown dealer inventory and lagged open interest cannot be repaired by an LLM. |
| Social-media NQ stack (`STDEV + GEX + OTE + RB + QT`) | **Reject as an implementation candidate until rules and evidence are supplied.** | The screenshot provides a result anecdote, not deterministic definitions, timestamps, full trades, costs, slippage, or a forward sample. |

The existing Vibe-Trading architecture is already more conservative in important ways. In particular, `scripts/gex_scanner.py` identifies GEX as a research proxy, discloses that open interest does not identify dealer inventory, requires open-interest coverage, avoids silently substituting volume for missing position size, and keeps execution disabled. Those controls should be preserved.

## Evidence standard used

This review used primary sources only: official product pages, official legal and methodology pages, official repositories and source code, official APIs, and Cboe's own market-structure research. Social screenshots were treated as primary evidence that a claim was made, not as proof that the claim is true.

Evidence was graded as follows:

- **High:** deterministic source code or legal terms, or exchange research using proprietary transaction data with disclosed methods.
- **Moderate:** vendor methodology with explicit assumptions and limitations but no independent audit.
- **Low:** vendor-created performance research without independent replication.
- **Very low:** social post, marketing claim, usage counter, or self-asserted test coverage without inspectable test artifacts.

## 1. TradeEcho

### What the platform actually offers

TradeEcho presents a unified market-analysis product with options positioning, flow, scanners, alerts, AI tooling, paper/review/live modes, and broker-linked execution surfaces. Its [platform overview](https://tradeecho.com/edge/platform-overview), [DealerEdge page](https://tradeecho.com/features/dealeredge), [Discovery scanner page](https://tradeecho.com/features/discovery), and [Cortex page](https://tradeecho.com/features/cortex) show that this is not merely a static data source. Cortex advertises Paper, Review, and Live modes, an approval queue, risk envelopes, a drawdown kill switch, and the ability to execute through linked accounts. Paper mode is the default and live activation requires an explicit phrase, which is a sensible product control, but the existence of execution authority materially increases integration risk.

Discovery advertises five scanners, 60-second rescans, and deduplication. The [Discovery alerts documentation](https://tradeecho.com/edge/discovery-alerts) describes opt-in alerts, per-signal thresholds, once-per-session deduplication with cooldowns, and an afternoon cutoff. These are useful workflow patterns, but they do not establish predictive edge.

### GEX/VEX methodology and limitations

TradeEcho's [Gamma Exposure methodology](https://tradeecho.com/methodology/gamma-exposure) is unusually candid and should be read before treating any displayed level as ground truth:

- The calculation uses live option-chain greeks, open interest, day volume, implied volatility, and spot inputs.
- Open interest is updated once daily before the open. Intraday movement therefore comes from spot, greeks, and volume rather than live position updates.
- Calls are assigned positive gamma and puts negative gamma under an assumed dealer-position convention.
- If open interest is missing, the methodology may fall back to day volume.
- The output is a signed relative measure, not a directly observed dealer inventory or a dollar-per-percent-move notional.
- VEX is vanna exposure derived from the same broad option-chain family; charm is also calculated.
- The dealer inventory sign is an assumption because actual dealer positions are not observed.
- If a clean zero crossing is unavailable, its flip calculation can fall back to the weakest net-GEX level; if usable data are absent, it can fall back to spot.
- The rating is a volatility-regime indication, not a directional forecast.
- The page explicitly warns about lagged open interest, assumed signs, vendor disagreement, and thin-chain fragility, and describes the output as context rather than prediction.

These disclosures are a reason to treat the data carefully, not a reason to discard it. They do, however, rule out using a TradeEcho level as a self-sufficient candidate generator or acceptance gate. A volume fallback is particularly unsuitable for the governed Vibe-Trading spine: current volume is flow, while open interest is a stock of positions. Substituting one for the other changes the meaning of the feature. Vibe-Trading should continue to fail closed when adequate open-interest coverage is unavailable.

### Published performance evidence

TradeEcho's [SPX GEX report](https://tradeecho.com/research/spx-gex-report) analyzes 62 SPX sessions, 21,947 minutes, and 382 crossings. It reports higher median minute volatility in low-rated regimes and notes that only 47% of crossings remained on the new side after 30 minutes. It also reports that every session touched the moving Anchor within 0.10%, while acknowledging that the Anchor recomputes and can migrate toward price; comparison with the final anchor was much less dramatic. The page correctly states association rather than causation and acknowledges that the sample covers one summer.

This is useful hypothesis-generating work, but it is first-party, covers a short regime, and was not independently audited or replicated in the sources reviewed. The moving-anchor statistic is especially vulnerable to interpretation error because a recomputed level can chase the observed price. Evidence grade: **low to moderate for descriptive association; insufficient for production alpha or execution authority**.

TradeEcho's [editorial policy](https://tradeecho.com/editorial-policy) also says displayed user results are individual, user-submitted outcomes rather than audited statements or typical results. Social P/L images should therefore never be promoted into evidence cards without the underlying event log.

### Licensing, data rights, and security posture

TradeEcho's [Terms of Service](https://tradeecho.com/terms-of-service) characterize the service and content as proprietary, grant a limited personal/noncommercial license, and prohibit automated extraction or scraping and unauthorized reproduction or exploitation. The terms also state that TradeEcho is not a broker or adviser, provide the service as-is, disclaim warranties, and place responsibility for linked brokerage activity on the user. Consequently:

1. Do not build a scraper, reverse-engineer the display, or automatically import TradeEcho content without a separate written license/API agreement.
2. Do not connect Vibe-Trading brokerage credentials or authorize TradeEcho/Cortex live execution as part of this project.
3. A manual evaluation may use human-recorded, minimal derived observations only if that use is permitted by the subscription terms; legal permission should not be inferred from technical accessibility.

The [risk disclosure](https://tradeecho.com/risk-disclosure) says market data and signals may be delayed, interrupted, or erroneous, AI output may be wrong, and users should not rely on the service as their sole source. That aligns with the proposed context-card-only treatment.

The [privacy policy](https://tradeecho.com/privacy-policy) describes general controls such as encryption, secure servers, and firewalls, and discloses collection of account, payment, technical, usage, and subscription information. The public materials reviewed did not provide a sufficiently detailed security architecture, independent assurance report, credential-scoping model, MFA policy, or incident-response evidence to justify delegating trading credentials. Absence from public documentation is not proof that these controls do not exist; it means they were not verified in this review.

TradeEcho's [copy-trading risk-engine documentation](https://tradeecho.com/edge/copy-trading-risk-engine) describes exposure caps, ticker/direction filters, a daily-loss gate on new activity, validation of timestamps and bid/ask ranges, and a minimum 30-day pilot history. These are sensible controls, but they are first-party descriptions rather than an independent security or execution audit. The daily-loss gate reportedly stops new activity while existing positions remain, so it should not be confused with a complete liquidation or universal kill switch.

### TradeEcho disposition

**No automated integration. No scraping. No broker connection. No execution authority.** If a paid evaluation is still desired, run a manual, quarantined, 30-session shadow study before making any subscription or integration decision:

- Freeze the observation before the candidate outcome is known.
- Record exact provider timestamp, spot timestamp, open-interest date, expiry set, strike window, displayed units, sign convention, and stated coverage.
- Capture GEX and VEX as a single dealer-positioning card.
- Compare against a predeclared baseline and preserve misses as well as hits.
- Evaluate alert timeliness, stale/missing states, level stability, and incremental information after existing Vibe-Trading cards—not screenshot P/L.
- Never let the vendor card bypass a veto, originate an accepted shadow position by itself, or become required for the scanner to run.

## 2. Fable Orchestrator

### The viral claim versus the repository

The supplied screenshots claim that installing “fable-orchestrator” runs Fable 5.1 “for FREE” on GPT-5.6 Luna subagents on every task and avoids agent usage limits. The likely referenced official repository is [mar3co/fable-orchestrator](https://github.com/mar3co/fable-orchestrator), whose [README](https://github.com/mar3co/fable-orchestrator/blob/main/README.md) does not support those claims.

The repository requires a sufficiently recent Claude Code installation and a paid subscription that includes Fable 5, plus authenticated Grok and Codex CLIs for its lanes. Its current routing sends implementation to Grok 4.6 or GPT-5.6 Sol, not GPT-5.6 Luna. The README also notes that faster Codex operation can consume substantially more credits. “Free,” “unlimited,” and “Luna on every task” are therefore either obsolete, exaggerated, or false relative to the reviewed repository version.

The repository offers anecdotal timing results from a very small number of tasks. That is evidence of a possible orchestration speed effect, not evidence of correctness, safety, unlimited capacity, or improved trading outcomes. The GitHub repository metadata observed on 2026-09-03 showed a project created in July 2026, last pushed in August 2026, with five stars, no forks, and one open issue. Evidence grade: **very low for reliability and performance**.

### License and security

The repository has an [MIT license](https://github.com/mar3co/fable-orchestrator/blob/main/LICENSE), so its code can generally be reused subject to preserving the license notice. Licensing is not the blocker; runtime authority is.

The [lane runner source](https://github.com/mar3co/fable-orchestrator/blob/main/scripts/run-lane.sh) places the Codex implementation lane in `workspace-write` and Codex review in read-only mode. However, the Grok implementation lane uses a bypass-permissions mode with a command-prefix deny list. The repository documentation itself warns that this deny list is not confinement and that equivalent command forms can bypass it. It also describes detached processes that can continue mutating the tree, with watchdog and process-group cleanup as mitigations. The [premise gate](https://github.com/mar3co/fable-orchestrator/blob/main/scripts/premise-gate.sh) fails open if `jq` is unavailable, relying on wrapper preflight as a secondary guard.

That authority model is inappropriate inside a trading repository containing credentials, generated state, scheduled jobs, or broker-facing code. A string-prefix deny list cannot establish a robust security boundary.

### Useful ideas that do not require installation

Fable's best ideas are process patterns already compatible with the governed spine:

- bounded roles rather than one agent performing every task;
- a premise/source gate before implementation;
- review by a different model or reasoning family;
- timeouts, process cleanup, and explicit completion reports;
- structured artifacts that separate claims, implementation, and review.

Vibe-Trading can express those patterns through its existing Codex/subagent workflow and tests without installing this repository or granting a CLI bypass mode. **Disposition: reject runtime installation; retain process concepts only.**

## 3. OpenMarket Price Action, Trend Signals, and Oscillator toolkits

### What was verified

OpenMarket describes kScript as its browser indicator language over chart OHLCV with real-time updates and a per-bar calculation budget. Its official [kScript documentation](https://openmarket.xyz/kscript) advises users to verify AI-generated code. The [public kScript hub](https://openmarket.xyz/hub/kscript) tells users they can read and adapt visible code, but this product copy does not itself grant a standard open-source license.

The official OpenMarket script API exposed exactly three public tools by Tisiphone matching the screenshot on 2026-09-03:

- [Trend Signals Toolkit](https://chart.openmarket.xyz/api/v1/scripts/6a981eab3d306e9eab22f6f9), version 1.0.2;
- [Oscillator Toolkit](https://chart.openmarket.xyz/api/v1/scripts/6a981eac913e2a64f13ce593), version 1.0.1;
- [Price Action Toolkit](https://chart.openmarket.xyz/api/v1/scripts/6a981eab913e2a64f13ce4b9), version 1.0.1.

All three were created on 2026-09-02, one day before this review; all were community scripts; the author metadata marked the scripter as unverified; and each was designated public, source-available, and featured. Platform usage counters are first-party operational metadata, not independent evidence of profitability. A purported 30-day-active-user field cannot represent a 30-day live history for a script created one day earlier.

### Source inspection

The source returned by the official API was inspected without importing it into Vibe-Trading:

| Toolkit | Approx. lines | Alerts | External HTTP/broker patterns observed | License marker observed |
|---|---:|---:|---:|---:|
| Trend Signals | 1,330 | 37 | 0 | 0 |
| Oscillator | 696 | 20 | 0 | 0 |
| Price Action | 1,912 | 39 | 0 | 0 |

The Trend toolkit evaluates at bar close and combines ATR-style volatility bands, a trend basis, and momentum. The Oscillator toolkit also evaluates at bar close and combines candle-derived waves, money flow, divergence, reversals, and a confluence score. The Price Action toolkit implements swing/pivot structure, breaks or changes of character, fair-value gaps, and liquidity-style events.

All three headers claim deterministic testing across engine versions, but no separately inspectable test harness or results were linked in the reviewed API payload. The claim is therefore self-asserted. No network or broker-call patterns were observed in the scripts, which lowers direct script-code risk inside the kScript runtime. It does not validate the platform, the signals, or their edge.

A crucial timestamp issue appears in the Price Action design: pivot swings require future bars for confirmation, then are visually drawn back at the historical pivot. That is a normal charting convention, but it becomes hindsight leakage if a backtest records the event at the pivot bar instead of the later confirmation bar. Any independent implementation must store both `pivot_at` and `detected_at` and make decisions only at `detected_at`.

### License and platform authority

No SPDX identifier or explicit license grant was present in any of the three script sources. Open or visible source is not automatically open-source software. OpenMarket's [Terms of Service](https://openmarket.xyz/terms) reserve rights and prohibit unauthorized scraping, reverse engineering, or exploitation of the platform or API. The same terms describe OpenMarket as an analytics and execution terminal that can route user-signed transactions through Polymarket/on-chain venues, and explicitly bar users in the United States from execution functionality. They also disclaim investment-adviser/broker status and best execution and cap liability.

Accordingly, **do not copy the source, scrape the hub, create an automated dependency on the API, or connect an execution account**. A concept can be independently implemented from first principles, but direct reuse needs an explicit license from the author/platform.

### Evidence quality and disposition

The toolkits have no public, auditable out-of-sample returns, full event ledger, costs, slippage, regime breakdown, or independent replication in the reviewed sources. Being featured and having community usage are not alpha evidence. Evidence grade: **very low**.

The concepts can still seed controlled hypotheses:

- timestamp-safe pivot confirmation with separate occurrence and detection times;
- modular BOS/CHoCH/FVG/sweep observations as descriptive price-structure features;
- a preregistered trend-versus-chop context feature;
- a separately evaluated oscillator divergence feature.

However, all three toolkits largely consume the same OHLCV stream. Their outputs are correlated transformations, not three independent evidence cards. If evaluated, they belong in one `technical_structure` family card so that counting them cannot manufacture consensus.

## 4. GEX/VEX as LLM “confluence”

The screenshot advice to paste GEX and VEX levels into an LLM can help summarize a scenario, but it cannot transform uncertain inputs into observed dealer positioning. Cboe's official article on [SPX 0DTE market impact](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options/) explains the conditional mechanism: long-gamma hedging can dampen movement, while short-gamma hedging can amplify it. It also emphasizes that high volume is not the same as high risk because the balance of buying and selling matters, and its proprietary-data sample found market-maker 0DTE gamma flows small relative to S&P futures liquidity.

Cboe's research paper on [option market-maker gamma exposure and gamma squeezes](https://cdn.cboe.com/resources/education/research_publications/gammasqueezes.pdf) uses proprietary trade information to infer market-maker positions and gamma. That methodology highlights what a public-chain heuristic lacks: signed participant flow and a defensible position estimate.

Therefore:

- GEX and VEX from the same provider, chain snapshot, and sign convention are **one evidence family**, not two confirmations.
- The LLM may summarize declared levels and assumptions but must not invent missing open interest, sign dealer inventory, repair stale timestamps, or infer a trade direction from a volatility-regime score.
- Provider agreement is not independence if providers share the same vendor feed, formula, or static open-interest snapshot.
- A dealer-positioning card may enrich or reduce confidence in a pre-existing candidate, but must never create acceptance on its own or bypass the veto/risk gate.

## 5. The NQ social result screenshot

The supplied screenshot reports a profitable NQ short using `STDEV + GEX + OTE + RB + QT`, with a fixed risk/reward rule. The artifact does not define the acronyms deterministically, provide machine-readable levels and timestamps, disclose all trades, include commissions/slippage, distinguish realized from maximum favorable excursion, or provide a forward/out-of-sample sample.

This is evidence that a result was posted, not evidence that a reproducible edge exists. The correct action is to request exact rules and a complete ledger, then preregister a replay and forward shadow test. No component should be implemented merely from the screenshot.

## 6. Concrete shadow-only adoption contract

### Dealer-positioning evidence card

If Vibe-Trading adds an external/manual GEX-VEX observation, use a schema at least this explicit:

```json
{
  "family": "dealer_positioning",
  "provider": "manual_or_named_provider",
  "observed_at": "RFC3339-with-offset",
  "spot_as_of": "RFC3339-with-offset",
  "open_interest_as_of": "YYYY-MM-DD",
  "expiries": ["YYYY-MM-DD"],
  "strike_window": {"min": 0.0, "max": 0.0},
  "sign_convention": "declared-provider-convention",
  "units": "declared-units",
  "weight_source": "open_interest",
  "coverage": {"contracts_seen": 0, "contracts_usable": 0, "oi_coverage": 0.0},
  "gex": {"regime": "positive|negative|mixed|unknown", "levels": []},
  "vex": {"regime": "positive|negative|mixed|unknown", "levels": []},
  "assumptions": [],
  "source_hash": "sha256-of-normalized-observation",
  "invalidation": [],
  "stale_reason": null
}
```

Required gates:

1. Reject naive or unparseable timestamps; never apply the machine's local timezone implicitly.
2. Reject unknown or stale spot/open-interest timestamps.
3. Reject undeclared units, sign conventions, expiry coverage, or strike coverage.
4. Reject volume-substituted position size for the governed card.
5. Record provider assumptions explicitly.
6. Deduplicate GEX and VEX into the same `dealer_positioning` family.
7. Keep `execution_enabled=false`; the card has no order authority.

### Technical-structure evidence card

If selected OpenMarket concepts are independently reimplemented, group them under one correlated family:

```text
family = technical_structure
subfeatures = [trend_regime, confirmed_pivot_structure, gap_or_sweep, oscillator_divergence]
event_time = detected_at                 # never the visually back-plotted pivot time
candidate_authority = false
veto_authority = false unless separately validated and explicitly promoted
```

Every subfeature needs an independently written definition, a versioned parameter set, unit tests for event timing, replay tests that prohibit future-bar access, and a forward shadow sample. Multiple subfeatures may explain one card; they must not count as multiple independent votes.

### Enforced lifecycle

The permitted flow remains exact and one-way:

1. **Candidate** — generated by an existing, named strategy with immutable candidate ID and event timestamp.
2. **Independent evidence cards** — grouped by source/input family; correlated transformations collapse to one card.
3. **Veto/risk gate** — fail closed on malformed, missing, stale, unknown, or degraded required inputs; an unfamiliar recommendation value is not approval.
4. **Shadow alert** — clearly labeled simulated; deduplicated and timestamped; no broker order or live-action wording.
5. **Simulated lifecycle** — deterministic entry/stop/target/expiry rules with no future knowledge.
6. **Reconciled outcome** — distinguish exact ledger values from estimates; exclude unreconciled positions from realized P/L.
7. **Rule update** — use only reconciled cohorts, require versioned evidence, and never rewrite past decisions.

Neither a TradeEcho observation, an OpenMarket-derived feature, nor an LLM summary may skip or reorder a stage.

## 7. Scanner and dashboard acceptance checks

Before any experimental component is enabled in shadow mode, the scanner and dashboard should demonstrate:

- `candidate_id`, `event_id`, and lifecycle-plan IDs remain deterministic and idempotent across refreshes.
- Each card shows provider, evidence family, data timestamps, freshness, coverage, assumptions, and validation status.
- GEX/VEX displays include the label **“estimated dealer exposure; dealer inventory not observed.”**
- A missing card is visibly `missing` or `unknown`, never silently green.
- A malformed kill-switch object, absent recent-regime approval, or unexpected consensus recommendation blocks new simulations.
- Pivot-derived events display both pivot time and detection/confirmation time.
- Alert state separates delivered, stale, rejected, and duplicate events.
- Shadow P/L separates exact reconciled ledger values from estimates and excludes pending records from realized totals.
- The dashboard is read-only with respect to broker/order state.
- A provider outage degrades the optional card without crashing the base scanner or silently changing the strategy.
- Full tests lock the exact governed pipeline order.

## 8. Final recommendation

There is no evidence-supported reason to add a new production dependency from the screenshots. The valuable output is narrower:

1. Preserve Vibe-Trading's existing fail-closed GEX coverage behavior and its explicit no-execution authority.
2. If desired, add a schema/test contract for one optional, manual dealer-positioning shadow card, with GEX and VEX collapsed into a single correlated family.
3. Independently implement only timestamp-safe price-structure concepts that fill a demonstrated gap; do not copy the OpenMarket scripts and do not treat three OHLCV transforms as independent votes.
4. Retain Fable's bounded-role and cross-review ideas without installing its permissive runtime.
5. Require all new hypotheses to pass the full governed spine and produce reconciled forward outcomes before any rule is updated.

This disposition protects the scanner from brittle vendor dependencies, protects the dashboard from overclaiming evidence, and keeps every new idea in the authorized sequence: `candidate → independent evidence cards → veto/risk gate → shadow alert → simulated lifecycle → reconciled outcome → rule update`.

