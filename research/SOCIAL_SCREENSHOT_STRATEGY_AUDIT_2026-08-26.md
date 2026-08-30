# Social Screenshot Strategy Audit — 2026-08-26

## Scope and evidence standard

This note audits the eight ideas visible in the supplied screenshots. A screenshot is useful for hypothesis discovery, but it is not performance evidence: it does not disclose the complete rule, denominator, losing trades, transaction costs, revisions, or whether an indicator repaints. Social performance statements below remain **unverified publisher claims**.

The implementation labels used here are deliberately narrow:

- **Implementable shadow layer** — the rule can be frozen, replayed without look-ahead, and kept unable to submit orders.
- **Research-only** — potentially measurable, but a required definition, source series, or data feed is still missing.
- **Reject** — not reproducible enough to justify even a new strategy lane, or its operational/security risk outweighs its incremental value.

| # | Screenshot idea | Decision | Vibe action |
|---|---|---|---|
| 1 | The Strat 30m/60m GC add levels | **Implementable shadow layer** | Extend the existing Strat challenger only after a GC-specific frozen spec; do not create a second engine. |
| 2 | Compression candle + “opposite” Phase Oscillator hypothesis | **Reject as supplied** | Preserve the existing rule that verified Saty data/parameters are required; an inversion is an ablation, not an edge claim. |
| 3 | BalconyTrading Vector range/entry boxes on NQ | **Reject** | Opaque commercial signal with no reproducible public rule or independently verifiable performance. |
| 4 | EZPZ AI TradingView Connector | **Reject vendor integration** | Reuse only the read-only chart-assistant pattern behind Vibe provenance/freshness gates; do not install the unsigned binary or grant order authority. |
| 5 | 5m ORB first-side sweep/rejection to opposite boundary | **Implementable shadow layer** | Add a frozen double-break ablation to the existing ORB-extension evaluator, not a production route. |
| 6 | Data Wicks + IWM supply/PDH/2m EMA confluence | **Implementable shadow layer, split** | Event wick is a context tag only; mechanically test the IWM PDH-zone/EMA subset as an ablation. |
| 7 | MNQ BSL sweep into M15 wick block, M1 refinement, 1:8 target | **Research-only** | Put sweep/block/entry and 2R/8R exits in one existing liquidity-sweep experiment family. |
| 8 | Running lessons file for failed/surviving strategies | **Implementable; already present** | Keep the structured immutable ledgers and shadow nominations; do not permit free-text lessons to self-modify production. |

## 1. The Strat 30m/60m GOLD “add” levels

### What the screenshot actually establishes

The supplied image is from the [TradeSniperSara profile](https://x.com/TradeSniperSara) and shows a GC1! 30-minute chart with a labeled “My 30min add,” a lower invalidation line, and higher target levels; it quotes an earlier “$GC 60m add coming up.” A searchable social mirror recovers the post text, but not a stable, verified rule definition: [TwStalker `#TheStrat` results](https://mobile.twstalker.com/hashtag/%23thestrat). The screenshot does **not** define the Strat scenario, when the initial position began, whether the “add” increases total risk, how the levels were calculated, or the contract roll.

GC risk is material. CME specifies standard Gold futures as 100 troy ounces with a minimum fluctuation of $0.10/oz, or $10 per tick: [CME Gold product overview](https://www.cmegroup.com/trading/metals/files/fact-card-gold-futures-options.pdf), [CME Gold contract slide](https://www.cmegroup.com/articles/files/2023/a-golden-opportunity-revisiting-gold-futures-and-options-webinar-slides.pdf). A pictured point distance therefore cannot be treated as harmless without contract count and stop distance.

### Mechanically testable version

Freeze, before replay:

1. continuous-contract construction and front-month roll rule;
2. RTH/ETH session and timezone;
3. daily Strat type (`1`, `2U`, `2D`, `3`) and full-timeframe-continuity direction;
4. completed 30-minute and 60-minute trigger definitions;
5. whether an “add” is pyramiding only after favorable movement or averaging into a loser;
6. total campaign stop, maximum aggregate risk, targets, and 60/120-minute outcome horizons.

The safe default is **no risk increase while the original tranche is underwater**. Each 30m/60m observation should also be recorded independently from any modeled campaign so an attractive combined path cannot hide a weak add-on rule.

### Existing repository overlap

This is not a new concept. `strategies/strat_30m_continuation.py` already classifies Strat bars, requires the completed 09:30–09:59 ET range, checks the prior-day break plus day/week/month open alignment, uses the opposite side of the 30-minute range as invalidation, and uses a prior-week extreme when available. `scripts/strat_30m_continuation_shadow.py` records a fixed 60-minute counterfactual and explicitly reports `shadow_challenger_only`. The canonical packet is `research/strategy_packets/strat_30m_continuation_v1.json`.

### Risk and decision

The screenshot is selected after the move and the level provenance is unknown. Extending the current evaluator to GC without a roll/session audit would create false precision. **Decision: implementable shadow layer only as a GC-specific extension of the existing Strat family; no live add logic, no new production lane, and no promotion weight from the screenshot.**

## 2. Compression candle and the “opposite” Phase Oscillator hypothesis

### What is identifiable

The screenshot from the [34 EMA Trader profile](https://x.com/Zabaroptik) says the author found the idea by testing “the literal opposite of the Phase Oscillator hypothesis” they started with. The quoted reply guesses “compression candle and phase oscillator.” It supplies no oscillator series, parameter set, threshold, direction mapping, entry, exit, or bar-close rule. No exact first-party post or public script definition could be reliably located from the image.

The closest identifiable instrument is Saty Mahajan’s Phase Oscillator. The creator has a first-party overview video, [Saty Phase Oscillator Indicator Overview](https://www.youtube.com/watch?v=9NO3dyWej38), and an official site, [Satyland](https://www.satyland.com/home). This does not prove it is the exact series or configuration in the screenshot.

### Existing repository overlap

`research/MILKMAN_STRATEGY_SUITE_PREREGISTRATION_2026-08-14.md` already states the correct fail-closed rule: compression must come from a **verified Saty Phase Oscillator series**, and Vibe must not guess proprietary/default compression parameters. The existing Bilbo candidates already define how a verified compression episode would be consumed.

### Testability, multiple testing, and decision

Once the author/source supplies exact inputs, freeze a paired family:

- original hypothesis;
- sign/direction-inverted hypothesis;
- identical universe, bars, costs, stops, exits, and evaluation window.

Testing “the opposite” after viewing a failure is legitimate hypothesis generation, but selecting whichever direction wins is another trial. It must be included in the family multiplicity count. Backtest overfitting and post-selection inflation are the exact problems addressed by [Bailey et al., *The Probability of Backtest Overfitting*](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) and [Bailey & López de Prado, *The Deflated Sharpe Ratio*](https://doi.org/10.2139/ssrn.2460551).

**Decision: reject as supplied.** Do not reverse-engineer colored ribbons or tune an oscillator until it resembles the screenshot. A later source-complete version may enter the existing compression experiment family as a frozen ablation.

## 3. BalconyTrading “Vector” ranges and entries on NQ

### What is identifiable

The screenshot from the [DaveTradesOpts profile](https://x.com/DaveTradesOpts) attributes the chart to “Vector by [BalconyTrading](https://x.com/BalconyTrading).” It shows repeated shaded range boxes and red markers, alongside promotional statements about a 100-point range and 250 points “secured.” Searchable profile mirrors describe Vector as a proprietary entry-timing script and refer to modes, stops, and targets, but do not disclose deterministic logic: [DaveTradesOpts mirror](https://twstalker.com/DaveTradesOpts). No public source code, versioned methodology, repaint disclosure, complete trade ledger, or independent results were located.

TradingView distinguishes open-source, protected, and invite-only publications; protected/invite-only logic cannot be audited from the chart: [TradingView published-script types](https://www.tradingview.com/support/solutions/43000482573-what-are-the-different-types-of-published-scripts/).

The dollar interpretation also matters. NQ is $20 times the index with a 0.25-point minimum tick: [CME E-mini Nasdaq-100 contract specifications](https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html). Thus 250 NQ points is $5,000 per contract gross, but the screenshot omits position size, stop, losing observations, and costs.

### What would be required to test it

A reproducible source would need to define: range start/end, box height, box reset, red-dot trigger, mode selection, confirmed-bar versus intrabar operation, repaint behavior, stop, target, timeout, and same-bar fill policy. Without those fields, reproducing the appearance would be image-fitting.

### Existing repository overlap and decision

Vibe already has range/regime routing and explicit shadow reversals in `strategies/flip_day_type_router.py` and `strategies/flip_shadow_setup_challengers.py`. The useful generic idea—**range state + confirmed trigger + explicit invalidation and target**—is already expressible without importing an opaque product.

**Decision: reject.** Do not buy, scrape, clone, or grade this indicator from promotional charts. Reconsider only if the publisher provides a stable rule specification or exportable signal history with version, timestamp, and repaint semantics.

## 4. EZPZ AI TradingView Connector and data-to-AI integration

### First-party product facts

The [EZPZ AI TradingView Connector](https://www.ezpztrading.com/ezpz-ai/tv-connector/) is a Windows bridge that says it controls TradingView Desktop through Chrome DevTools Protocol (CDP), can read chart/OHLCV state, change symbol/timeframe, create drawings and alerts, inject/compile Pine, take screenshots, and expose proprietary EZPZ datasets to supported AI providers. It supports bring-your-own API keys on some tiers. The page also tells users to bypass Windows SmartScreen because its distributed binary is unsigned. That is vendor self-description, not an independent security attestation.

CDP is powerful by design. The official protocol exposes browser debugging endpoints and runtime evaluation: [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/), [CDP Runtime domain](https://chromedevtools.github.io/devtools-protocol/v8/Runtime/). A debugging port therefore expands the local attack surface and should not be exposed to untrusted processes or networks.

TradingView already supports a narrower integration surface through webhook alerts. Its official documentation says webhook alerts POST to a supplied URL, require 2FA, can occasionally fail, and should not carry credentials: [TradingView webhook alerts](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/), [TradingView webhook authentication](https://www.tradingview.com/support/solutions/43000680459-webhook-authentication/). Strategy alerts run from a server-side copy and must be recreated when settings change: [TradingView strategy alerts](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/).

### Existing repository overlap

`research/claude_tradingview_mcp_trading_deep_dive_2026-06-30.md` already reached the appropriate architecture decision: use TradingView automation for screenshots, Strategy Tester/Pine compile loops, and visual validation; never let that interface place orders. The current `frontend/src/pages/Agent.tsx` connector prompts are read-only by default, while `strategies/trading_dashboard.py` and `scripts/generate_dashboard.py` expose read-only validation/report surfaces.

### Decision

The useful concept is not the binary; it is a **provenance-qualified read-only chart adapter**. Any adapter must have a symbol/timeframe/session echo, observation timestamp, maximum data age, source ID, explicit tool allowlist, secret isolation, audit log, and `can_submit_orders=false`. Model-written Pine must be treated as untrusted code and validated separately.

**Decision: reject the EZPZ binary/data integration for Vibe.** Do not bypass SmartScreen, send Vibe/Alpaca secrets to prompts, expose CDP outside loopback, or authorize browser-driven order submission. Existing authenticated webhooks/connectors are the safer base; a read-only UX enhancement can be implemented independently of this vendor.

## 5. Five-minute ORB double break: liquidity sweep, rejection, opposite boundary

### First-party definition and what the 69% does not prove

The screenshot from the [WilliamTradesNG profile](https://x.com/williamtradesng) describes a New York-open move above a swing high and ORB high, rejection, short entry, and ORB-low target. The attached Edgeful panel shows a 69% double-break figure. That number is a filtered, point-in-time descriptive statistic, not the conditional expectancy of the pictured entry after costs.

Edgeful defines a double break as both ORB sides breaking in the same measured session and warns that wick/close criteria, session, and timezone must match: [ORB breakout and breakdown levels](https://help.edgeful.com/en/articles/14436889-orb-breakout-and-breakdown-levels-explained). Its own historical examples show severe regime drift: ES double breaks fell from 81% in Q1 2024 to 50% in Q4 2024: [adapting to changing market conditions](https://www.edgeful.com/blog/posts/adapting-to-changing-market-conditions). Another Edgeful example explicitly describes trading the first-side break toward the other boundary when the observed double-break rate was 61%, then shows that rate later falling to 35%: [spotting changing futures market environments](https://www.edgeful.com/blog/posts/spot-changing-futures-market-environments-with-edgeful).

Importantly, Edgeful’s standard automated ORB algorithm takes only the first valid breakout and one trade per day; it does not automatically endorse a second-break discretionary entry: [Using the ORB algo](https://help.edgeful.com/en/articles/12858391-using-the-orb-algo).

### Mechanically testable version

Freeze: symbol; NY session/timezone; five completed one-minute bars; wick versus close break; minimum sweep/extension in ORB fractions; prior-swing definition; close-back-inside rejection; next-bar/lower-high confirmation; stop beyond sweep extreme; ORB-opposite-boundary target; end-of-session timeout; one observation/day; commissions/slippage; and first-touch ambiguity handling.

Report both:

- unconditional probability that the opposite ORB side is touched after the first break;
- trade expectancy conditional on the fully confirmed sweep/rejection entry.

Those are not the same quantity. Use rolling, walk-forward date windows; weekday filters are additional hypotheses, not free improvements.

### Existing repository overlap and decision

`strategies/flip_shadow_setup_challengers.py` already includes `evaluate_orb_extension_reversal` (completed 5m ORB, at least one ORB-range extension, structural reversal, stop beyond the extreme, and a return-to-the-broken-side boundary/2R target) and `evaluate_level_sweep_reversal` (failed prior-level break, next-bar confirmation, structural stop and target). Both are explicitly `shadow_challenger_only` and cannot submit orders. Existing resolved observations also appear in `data/confirmed_momentum_delayed_entry_results.json`. The remaining test gap is important: the current ORB evaluator targets the boundary that was initially broken, **not the far/opposite ORB boundary** shown in the double-break thesis.

**Decision: implementable shadow layer, but only as a preregistered ablation of the existing evaluator.** Compare `ORB extension only` versus `extension + prior-swing sweep` versus `extension + sweep + close-back rejection`, and compare the existing near-boundary/2R exit with the far-boundary double-break exit. Do not create a duplicate production scanner and do not hard-code the screenshot’s 69%.

## 6. Data Wicks plus IWM supply-zone/PDH/2m EMA trend

### 6A. CantoLab Data Wicks

The first-party [Data Wicks [CantoLab] TradingView page](https://in.tradingview.com/script/Zacxps8w-Data-Wicks-CantoLab/) says the protected-source indicator marks unusually large wicks printed during high-impact news windows. It offers an adaptive recent-volatility threshold or a manual point threshold. The author states the belief that price often returns to these levels and explicitly tells users to test before relying on it. The closed source means the adaptive formula cannot be independently reproduced from the page.

CME research supports the **event tag**, not the fill claim: labor, inflation, and retail-surprise releases can materially change first-, five-, and ten-minute futures activity: [CME, economic indicators that most impact markets](https://www.cmegroup.com/insights/economic-research/2025/economic-indicators-that-most-impact-markets.html). It does not establish that an event wick will later be revisited.

A valid study should match event wicks to non-event wicks by instrument, time of day, ATR-normalized wick size, direction, and volatility regime. Measure revisit survival curves at 5/15/30/60 minutes and by session close; include observations never revisited rather than deleting them. The event-wick level is a context feature, never an automatic target.

### 6B. IWM supply rejection, PDH flip, and 2-minute EMA trend

The screenshot’s text is recoverable on the [Team2Trading profile mirror](https://instalker.org/Team2Trading): reject the supply zone, observe prior-day high (PDH) flip back to resistance, then follow the 2-minute EMA trend. A prior first-party post, recoverable at [Team2Trading status 1905768127163732029](https://x.com/Team2Trading/status/1905768127163732029) and its [thread mirror](https://threadreaderapp.com/thread/1905768083371008327), describes the zone as the 15-minute HOD/PDH wick through the following candle body and uses 13/48/200 EMAs on the 2-minute chart. The exact current screenshot status was not recoverable, so these earlier rules are supporting method evidence, not proof of the pictured trade.

Freeze the zone boundaries, minimum penetration, close-back rejection, PDH tolerance, EMA calculation, bearish ordering (`EMA13 < EMA48 < EMA200`), minimum normalized spacing, entry at completed 2-minute close, stop above the rejected zone, next structural target, timeout, and one signal per zone. Compare the full stack against each isolated component.

### Existing repository overlap and decision

`strategies/flip_bot.py` already computes PDH/PDL proximity and VWAP/EMA alignment; `strategies/flip_shadow_setup_challengers.py` already evaluates failed level sweeps; `scripts/candlestick_context_scanner.py` and `scripts/market_structure_intelligence.py` already provide contextual structure. The CantoLab equal-high/low script previously supplied by the user is also a reproducible source for tick-tolerant liquidity levels: [Equal Highs and Lows with Relative [CantoLab]](https://www.tradingview.com/script/3BeHr2qT-Equal-Highs-and-Lows-with-Relative-CantoLab/).

**Decision: implementable shadow layer, split by role.** Add `event_wick_context` only as a research tag using Vibe’s own transparent ATR-normalized formula; add the IWM PDH-zone/EMA ordering as a frozen filter ablation if its exact fields are not already emitted. Do not recreate CantoLab’s closed formula, infer a guaranteed wick fill, or promote from one annotated winner.

## 7. MNQ BSL sweep into M15 wick/rejection block, M1 entry, fixed 1:8

### What the screenshot establishes

The supplied post appears to be from the [MzRaine profile](https://x.com/MzRaine_) and says price swept buy-side liquidity (BSL) into an M15 wick/rejection block, then used M1 for entry refinement, a ten-point stop, and a fixed 1:8 target at the discount of the dealing range. An exact public status and complete methodology could not be independently recovered; the profile identification is based on the supplied image/context. The claim is one selected outcome.

A 1:8 label is a payoff target, not an observed expectancy. With a ten-point stop it implies an 80-point favorable target before costs, but the screenshot does not show how many qualified setups failed, whether the stop was actually executable, or how same-minute stop/target ambiguity was resolved.

### Mechanically testable version

Freeze without look-ahead:

1. BSL as a prior confirmed pivot/equal-high cluster with explicit left/right bars and tick tolerance;
2. M15 wick-block boundaries (body-to-high or entire candle), minimum wick/body ratio, and expiration;
3. sweep distance of at least one tick plus an M15 close back inside;
4. M1 market-structure shift and optional retest, all on completed bars;
5. stop beyond the sweep extreme rather than an assumed universal ten points;
6. dealing-range endpoints and the exact “discount” target;
7. target-before-stop replay using lower-timeframe data, with conservative handling when ordering is unknowable;
8. 2R and 8R exit arms under the same entry so exit selection is counted as another hypothesis.

### Existing repository overlap and decision

The core already overlaps `strategies/flip_shadow_setup_challengers.py::evaluate_level_sweep_reversal`, `scripts/liquidity_sweep_scanner.py`, `scripts/market_structure_intelligence.py`, `research/MES_SMC_PREREGISTRATION_2026-07-19.md`, and the existing MNQ SMT/CISD/FVG preregistrations under `research/preregistrations/`. A nested M15→M1 version belongs in that experiment family, not a fresh independent family.

**Decision: research-only.** Run a factorial ablation—sweep only; sweep + M15 block; sweep + block + M1 shift—and compare 2R versus 8R exits with BH-FDR/multiple-testing control. Do not grade the composite until it adds out-of-sample value above the simpler sweep layer.

## 8. Running lessons file for failed and surviving strategies

### Useful principle and unsafe interpretation

The screenshot from the [DaviddDotTech profile](https://x.com/DaviddDotTech) recommends that an agent record why strategies fail, record what survivors share, and read the file before building again. The useful principle is durable, contrastive evidence. The unsafe interpretation is to let an LLM rewrite production strategy parameters from narrative memory after every outcome.

### Existing repository overlap

Vibe already implements a stronger form:

- `scripts/closed_trade_postmortem.py` creates read-only outcome, sizing, exit, stop-discipline, and capture lessons;
- `scripts/loop_closure_report.py` writes the canonical append-only `data/trade_lesson_ledger.jsonl`, deduplicates lesson IDs, marks severity/status, and routes open lessons to counterfactual shadow trials with `promotion_authority=none`;
- `scripts/self_learning_edge_loop.py` aggregates repeated patterns but explicitly sets `automatic_parameter_changes=false`, `production_config_mutation_allowed=false`, and requires preregistration plus minimum forward outcomes for shadow nominations;
- `scripts/flip_bot_learning_report.py` distinguishes entry/regime failures, closed-trade reinforcement, capture gaps, same-day re-entry losses, and shadow asymmetry, while warning that win rate alone is insufficient;
- `scripts/daily_edge_orchestrator.py` remains read-only and treats screenshot hindsight as something to measure, not an execution trigger.

### Safe incremental fields and decision

If the canonical schemas do not already contain them, the next version can add: falsification reason, survivor commonality, cohort/spec version, source observation IDs, recurrence count, evidence eligibility, counterfactual required, owner, and resolution timestamp. “Survivor commonality” must be computed against failures from the same eligible cohort to avoid survivorship bias. No lesson may erase a loss, change a frozen spec, alter risk, or promote its own proposed fix.

**Decision: implementable and already implemented.** Improve the structured reporting schema only when a concrete field gap is demonstrated; do not add a second free-text lessons file or an autonomous self-modification instruction.

## Cross-cutting experiment rules

1. **One family per economic idea.** Opposite directions, added filters, alternate timeframes, and 2R/8R exits are candidates within the same family, not independent discoveries.
2. **Point-in-time inputs only.** Retain symbol, contract, roll, session, timezone, source timestamp, formula version, and data freshness.
3. **Completed-bar semantics.** No entry may use an M15/M5/M1 close before that bar closes; conservative same-bar ambiguity is mandatory.
4. **No screenshot calibration.** Thresholds must come from a frozen source rule or a predeclared coarse grid, never visual matching to the pictured winner.
5. **Costs and capacity.** Include futures commissions/slippage and dollar-per-point conversion; options variants additionally require point-in-time NBBO and executable fills.
6. **Ablations before composites.** Each new confluence must beat its simpler layer out of sample; otherwise it adds complexity, not evidence.
7. **Selection-aware statistics.** Report all variants, BH-FDR within the family, Deflated Sharpe, PBO/walk-forward stability, and performance with the top 1%/5% winners removed. Multiple-testing risk is not theoretical: [Harvey, Liu & Zhu, *…and the Cross-Section of Expected Returns*](https://www.nber.org/papers/w20592).
8. **Authority remains shadow-only.** None of these screenshots, vendor tools, or lesson summaries may change production gates, sizing, or broker orders.

## Final priority order

1. **Reuse and ablate the existing 5m ORB extension reversal** with a first-side swing-sweep/rejection flag.
2. **Extend the existing Strat evaluator to GC only after a frozen futures-roll/session/risk spec.**
3. **Add transparent event-wick context and the IWM PDH-zone/EMA filter as separate fields**, not a bundled signal.
4. **Keep the MNQ M15→M1 1:8 setup research-only** inside the current liquidity-sweep family.
5. **Keep the current structured learning loop; do not add autonomous mutation.**
6. **Reject the opaque Vector signal, unspecified opposite-Phase claim, and EZPZ binary integration.**

No production code, registry, scheduler, execution, or risk-setting change is authorized by this audit.
