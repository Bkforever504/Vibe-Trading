# Codex To Claude Code: Edge And Profitability Research Handoff

Date: 2026-08-11

## Objective

Turn the existing trading system into a faster evidence-producing machine
without weakening execution, capital, or broker-reconciliation safeguards.

This handoff does not claim that profitability is guaranteed. The current
system is operationally strong but still evidence-limited. The next useful
work is to increase the quantity and quality of executable-quote outcomes,
attribute where returns are created or lost, and retire hypotheses that do
not survive out-of-sample costs.

## Hard Safety Boundaries

- Do not submit, replace, cancel, or route broker orders while implementing
  this handoff.
- Do not enable a new strategy or raise sizing.
- Do not grant Alpaca indicative quotes execution authority.
- Do not relax reconciliation, liquidity, event, portfolio, warning, OPRA,
  or kill-switch gates.
- Do not promote any result from social media, two successful replays, or a
  favorable in-sample backtest.
- Do not add a daily dollar target or force a trade.
- Do not expose API keys, tokens, account identifiers, or broker payloads in
  logs, tests, commits, or chat.

## Current Honest State

### Operations

- Elite readiness score: 7.1/10.
- Operational integrity: 10/10.
- Risk controls: 10/10.
- Autonomous safety: 10/10.
- Signal stack health: 61 OK, 0 stale, 0 missing, 0 error, 1 disabled.
- Execution gate audit: passed, 102 signals, 0 issues, 1 warning.
- Full suite before this handoff: 4,546 passed, 4 skipped.
- Targeted OPRA replay and options twin tests after the handoff fix: 47 passed.
- Final full suite after the handoff fix: 4,547 passed, 4 skipped.
- No orders were submitted.

### Evidence

- Flip learning report: 13 post-hardening closed trades, 61.5% win rate,
  +$2,312 reported PnL, 4.78 profit factor, +$177.85 expectancy. This is a
  promising but very small forward sample, not proof.
- Options shadow twin: 3 resolved candidates over 2 dates, -$605 before fees,
  -$201.67 expectancy, 0.0678 profit factor, and 1/3 wins. The result is too
  small for inference and currently negative.
- Options shadow entry-friction estimate: average 5.77%, worst 6.77%.
- Options shadow close-friction estimate: average 3.86%, worst 100%.
- Licensed Databento OPRA curriculum: 2/2 resolved call-spread lifecycles from
  one date, both profitable after doubled and tripled fees. The review gate
  correctly fails because there are only two outcomes and no development
  blocks.
- Market-structure research: no current cohort survives holdout, doubled
  costs, and top-5%-outlier removal.
- Historical scenario curriculum remains negative out of sample.
- Exit quality remains the weakest operating category: 4/10, with only three
  complete paths and zero average profit capture in the current report.

### Current Data Assets

The repo already contains the necessary adapters. Do not create duplicates.

- `scripts/tradier_options_data.py`: read-only Tradier production options
  quote adapter. It has no order endpoints.
- `scripts/probe_tradier_options_data.py`: credential-safe read-only probe.
- `scripts/fetch_databento_options_nbbo.py`: cost-guarded, candidate-scoped
  Databento `OPRA.PILLAR` `cbbo-1s` acquisition.
- `research/options_nbbo_curriculum.py`: executable-side lifecycle replay.
- `scripts/run_nightly_options_nbbo_evidence.ps1`: incremental nightly fetch
  with a default maximum cost of $0.05 per run.
- `scripts/options_shadow_twin.py`: forward candidate and mark lifecycle.

The current Databento manifest covers four exact SPY/QQQ contracts, 207,997
accepted consolidated quote observations, and two candidates. The recorded
cost estimate was $0.031057. This confirms candidate-scoped OPRA acquisition
is financially practical. It does not provide enough outcomes yet.

## Research Performed

### Last-30-Days Community Scan

Coverage window: 2026-07-12 through 2026-08-11.

- Reddit: 25 threads, 859 upvotes, 1,064 comments.
- Hacker News: 15 stories, 548 points, 426 comments.
- X failed with HTTP 403.
- YouTube was unavailable because `yt-dlp` was not installed.
- TikTok and Instagram were unavailable because no supported API key was
  configured.

The useful community discussions centered on validating a genuine edge,
killing failed strategies, low-delta premium selling, broker execution, and
loss cases. They provide research leads, not return evidence. The scan was
only 3/5 on core-source coverage and included irrelevant Hacker News matches,
so it must not be used for strategy promotion.

Raw result:

`C:\Users\kenne\Documents\Codex\2026-07-29\i-cleaned-the-actual-profitability-leaks\last30days-output\systematic-options-trading-edge-execution-profitability-raw-v3.md`

Relevant discussions:

- https://www.reddit.com/r/algotrading/comments/1uv285c/swing_traders_how_do_you_find_and_validate_a/
- https://www.reddit.com/r/algotrading/comments/1vi4jsf/how_many_strategies_did_you_kill_before_the_one/
- https://www.reddit.com/r/thetagang/comments/1vibbr1/not_a_bad_month_3k/
- https://www.reddit.com/r/options/comments/1vgbhgl/etrade_vs_schwab_for_option_execution/

### Recent Primary Research

1. Passive execution is an optimization problem, not a fixed limit-order
   ladder. Fill probability falls with distance from mid, while adverse
   selection and opportunity cost rise as the order waits. This directly
   supports measuring quote distance, fill probability, post-fill movement,
   and non-fill cost.
   https://arxiv.org/abs/2607.28323

2. A recent 3,909-backtest 0DTE study reports many attractive strategy
   results, but the distribution is extremely right-skewed and the authors
   warn about small samples, selection bias, and overfitting. Credit spreads
   reportedly had stronger risk-adjusted results than iron flies, while iron
   flies had larger per-trade returns and lower win rates. Treat this as a
   hypothesis source, not a forward guarantee.
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7055179

3. Recent SPX research finds algorithmic retail 0DTE complex-order activity
   clusters at hour and half-hour timestamps and dissipates quickly. Test the
   clock footprint as an execution or context feature in shadow only.
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6480379

4. A 146-fold S&P 500 walk-forward study finds strategy dominance depends on
   realized-volatility and momentum regimes. This supports regime-conditional
   reporting rather than one aggregate Sharpe ratio.
   https://arxiv.org/abs/2606.31251

5. A recent FOMC study combines 30-second SPY/SPX options with Powell audio,
   video, and text and reports out-of-sample event results after full spread.
   It has only 60 press conferences and is event-specific. Keep it as a later
   shadow research lane, not a daily strategy.
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6990562

6. Cboe reports that Q2 2026 listed-options volume reached 72.8 million
   contracts per day and SPX 0DTE volume nearly tripled from early 2024. More
   volume means more opportunity to study execution; it does not imply an
   exploitable directional edge.
   https://www.cboe.com/insights/posts/state-of-the-options-industry-options-market-continued-to-break-records-in-q-2-2026

### Data-Authority Findings

- Alpaca Basic provides only an indicative options feed. Algo Trader Plus is
  $99/month and includes OPRA. Never infer OPRA authority from an Alpaca REST
  snapshot unless the entitlement and provenance explicitly say OPRA.
  https://docs.alpaca.markets/us/docs/about-market-data-api
- Tradier provides real-time consolidated stock and options data only to
  brokerage account holders. Sandbox options data is delayed. The existing
  adapter intentionally supports production market data only.
  https://docs.tradier.com/docs/market-data
- Databento `OPRA.PILLAR` provides consolidated last sale and national BBO for
  ETF, single-name, and index options, plus point-in-time definitions. Its
  pay-as-you-go historical pricing remains available.
  https://databento.com/docs/examples/options/equity-options-introduction/opra
  https://databento.com/blog/introducing-new-opra-pricing-plans

## Root Diagnosis

The system's main constraint is no longer scheduler reliability. It is the
combination of low evidence throughput, high hypothesis count, and weak
attribution.

1. Thirteen forward outcomes cannot calibrate dozens of gates, features,
   strategy variants, time buckets, and exits.
2. The system usually creates evidence only after a complete strategy
   candidate forms. Hard gates therefore protect capital but also reduce the
   counterfactual sample.
3. Signal quality, option structure, quote friction, and exit policy are
   mixed into one PnL number. We cannot tell which layer creates or destroys
   expectancy.
4. Two OPRA outcomes prove the replay plumbing, not the strategy.
5. The exit layer has fewer complete paths than the entry layer and therefore
   cannot yet be optimized honestly.
6. Social-media winners have unknown denominators, deleted losses, hidden
   sizing, and unverified fills. Copying them directly would import selection
   bias, not edge.
7. GEX, skew, IV rank, FVG, RSI, ORB, and candlestick labels are features.
   None is an edge until a frozen rule survives point-in-time data, executable
   prices, costs, holdout, and forward validation.

## Frozen Strategy Portfolio

Do not expand the execution portfolio beyond these three families until the
evidence program is complete.

1. `vrp_defined_risk`: 30-45 DTE SPY put credit spread or iron condor when
   same-horizon IV exceeds a forward RV estimate net of friction and events.
2. `flip_directional_0dte`: current SPY directional system, unchanged and
   paper-only under existing gates.
3. `pin_range_0dte`: SPY/SPX iron fly around a point-in-time pin hypothesis,
   shadow only. No GEX label may substitute for qualified point-in-time
   inputs.

All other indicators remain telemetry or preregistered research. They do not
receive execution votes by default.

## Implementation Program

### P0: Build A Matched Counterfactual Evidence Factory

Create `scripts/options_evidence_factory.py` with no broker-trading imports.
It should form read-only candidates from every eligible base setup, including
setups blocked by a downstream gate.

For each base setup, create a shared `setup_id` and matched expressions:

- the current strategy expression;
- a defined-risk alternative with the same directional thesis;
- a no-trade benchmark;
- an iron-fly expression only when the frozen pin/range rule qualifies.

This lets us decompose whether a failure came from direction, volatility
pricing, structure choice, or execution. A blocked counterfactual is evidence,
not permission to trade.

Required fields:

- schema version and immutable candidate ID;
- `setup_id`, source strategy, symbol, timestamp, and decision hash;
- every gate state and warning state;
- point-in-time spot, VIX state, IV/RV inputs, events, and regime label;
- concrete OCC legs, side, ratio, strike, expiry, DTE, and selection time;
- executable entry credit/debit and quote provenance;
- max profit, max risk, breakevens, profit target, stop, and time exit;
- expression type and parent setup ID;
- `execution_enabled: false` and `can_submit_orders: false`.

Do not create a candidate when contracts or quotes are missing. Record an
explicit unavailable row instead of imputing contracts, mid fills, or
underlying returns.

Tests must prove:

- blocked setups still create read-only counterfactuals;
- no execution module can be reached;
- no future contract or quote timestamp is accepted;
- strategy expressions share a stable parent setup ID;
- missing OPRA evidence stays unavailable.

### P0: Expand The Existing OPRA Lifecycle, Not The Tool Count

Use the existing pipeline:

1. `scripts/options_shadow_twin.py`
2. `scripts/fetch_databento_options_nbbo.py`
3. `research/options_nbbo_curriculum.py`
4. `scripts/run_nightly_options_nbbo_evidence.ps1`

Codex added `iron_fly` to the OPRA curriculum and added a four-leg
executable-quote regression test. Preserve that change.

For forward candidates, retain `cbbo-1s`, candidate-scoped symbols, and the
existing $0.05 nightly cap. For broad retrospective discovery, use
`cbbo-1m` plus point-in-time instrument definitions. Do not request full-chain
one-second history across years.

Add coverage reporting by strategy, date, entry, complete lifecycle, and
rejection reason. The system needs at least 30 resolved outcomes per strategy
across 20 dates before an initial diagnostic review.

### P0: Verify Forward Consolidated Quote Coverage

If a production Tradier brokerage token already exists, run only:

`python scripts\probe_tradier_options_data.py`

Requirements:

- never print the token;
- reject sandbox or delayed provenance;
- compare quote timestamps and widths with same-day Databento history when
  available;
- remain read-only;
- do not switch execution providers automatically.

If no production token exists, report the blocker. Do not open an account,
purchase a plan, or weaken the OPRA gate.

### P1: Attribute PnL By Layer

Create `scripts/options_edge_attribution_report.py`.

For every resolved matched setup, report:

- `signal_edge`: underlying move relative to the frozen thesis;
- `volatility_edge`: entry IV minus horizon-aligned realized volatility,
  preserving the current friction and event adjustments;
- `structure_edge`: difference between matched option expressions;
- `entry_execution_edge`: executable entry versus midpoint;
- `exit_execution_edge`: executable close versus midpoint;
- `management_edge`: actual exit policy versus frozen alternative exits;
- `total_net_pnl`: executable PnL after all fees.

The parts do not have to sum perfectly when interactions exist. Record an
interaction residual rather than forcing attribution.

### P1: Build An Exit Policy Lab

Create `research/options_exit_policy_lab.py` using only resolved OPRA paths.

For every candidate, record:

- premium and underlying MFE/MAE;
- time to MFE, MAE, target, stop, and expiry cutoff;
- spread width and quote completeness at each observation;
- fixed-profit, fixed-stop, structural-stop, and time-stop counterfactuals;
- close friction and non-fill risk;
- censoring when the lifecycle is incomplete.

Use chronological walk-forward evaluation. Do not select a policy from the
same dates used to estimate it. Do not optimize hundreds of target/stop pairs.
Use a small preregistered policy set and count every attempted policy in the
trial ledger.

### P1: Build An Execution Experiment

Create `research/options_limit_execution_lab.py`.

Estimate, by structure and time bucket:

- fill opportunity at bid, midpoint, and fixed concessions;
- probability of no fill;
- adverse price movement 1, 5, 15, and 60 seconds after a hypothetical fill;
- opportunity cost after a non-fill;
- net utility after fees and missed trades.

Use matched shadow quote policies on the same setup. Optimize net expectancy,
not fill rate. Report combo-level limitations because summed-leg executable
prices are a conservative proxy and not a complex-order-book fill claim.

### P1: Feature Austerity And Ablation

Create one registry for every feature that can influence a decision:

- `execution`: frozen and permitted to vote;
- `research`: logged but cannot vote;
- `retire`: no longer scheduled or scored;
- `safety`: hard block only.

Cap the execution feature set at ten per strategy. For each feature, require a
chronological ablation showing incremental net value after doubled costs and
outlier removal. Correlated features count as one family for multiple-testing
purposes. A feature that cannot be evaluated because `n` is too small remains
research-only.

### P2: Regime And Clock-Footprint Research

Add a compact regime state using only information known at the decision time:

- realized volatility state;
- trend/momentum state;
- liquidity/spread state;
- event state.

Use an online change-point or drift flag to invalidate stale calibrations.
Report results by regime, but do not create dozens of tiny buckets.

Preregister one SPX clock-footprint study around hour and half-hour complex
order spikes. Test it as:

- an entry-avoidance window;
- an execution-cost state;
- a short-horizon reversal/context feature.

Do not assume the published footprint is profitable or directionally useful.

Keep FOMC multimodal research separate. It is low-frequency, event-specific,
and must never share training data with ordinary sessions.

## Evidence And Promotion Standard

Keep the existing gates. Add no automatic promotion path.

### Diagnostic Review

- at least 30 resolved outcomes per strategy;
- at least 20 distinct trading dates;
- at least 80% complete OPRA lifecycle coverage;
- zero look-ahead violations;
- complete contract-selection provenance.

### Paper-Sizing Review

- at least 100 resolved outcomes per strategy;
- at least 60 distinct dates;
- positive chronological holdout expectancy after fees;
- positive expectancy after doubled costs;
- positive expectancy after removing the top 5% of trades;
- no single date, time bucket, or regime explains most profit;
- calibrated probabilities improve Brier/log loss out of sample;
- drawdown and loss streak fit the existing risk budget.

### Profitability-Evidence Review

- preserve the scorecard standard of at least 200 outcomes and 120 days;
- include forward broker-fill evidence, not historical OPRA alone;
- require stable results across chronological blocks and relevant regimes;
- require DSR and multiple-testing controls already present in the repo;
- require human review before any execution or sizing change.

## Codex Implementation Completed 2026-08-11

Codex completed the P0 evidence pipeline and the P1 attribution report. Do not
rebuild these components.

- `scripts/options_evidence_factory.py` now creates stable matched setup IDs,
  records primary and component expressions, records no-trade benchmarks, and
  preserves explicit unavailable reasons. Blocked setups remain read-only
  evidence. Future contract-selection and quote timestamps fail closed.
- `scripts/options_shadow_twin.py` now preserves setup, expression, gate,
  warning, regime, event, quote-provenance, stop-policy, and evaluation-end
  metadata. Time-exit-only policies no longer receive an invented credit stop.
- `strategies/iwm_options_bot.py` sends iron-condor, put-spread, and call-spread
  candidates through the matched factory while preserving safety-decision
  linkage and labeling incomplete legacy candidates as not review eligible.
- `scripts/options_edge_attribution_report.py` reports signal telemetry,
  maturity-matched volatility inputs, entry and exit spread friction, matched
  structure outcomes, and management-policy availability. It prefers licensed
  OPRA outcomes and never forces additive attribution.
- `scripts/run_options_shadow_twin.ps1` and
  `scripts/run_databento_options_nbbo_curriculum.ps1` now refresh the coverage
  and attribution reports without changing execution authority.
- The SPY 0DTE PM, iron-condor, and theta-harvester shadows now use true
  executable spread entry and close sides rather than optimistic midpoint or
  short-leg proxies.
- Equal-width iron-condor max loss is now one wing width minus total credit,
  not the impossible sum of both fully breached wings.
- PM and iron-condor monitor decisions now persist marks and executable closes
  to state and ledger files. Missing/malformed quotes, legacy incomplete state,
  unreadable state, and duplicate open shadows fail closed. `--check` with no
  state cannot fall through into entry formation.
- Theta-harvester management now records an executable 21-DTE time exit and
  its actual 50%-profit/1x-credit-stop policy in matched evidence.

Current matched SPY-options evidence is honestly empty: zero matched setups,
zero resolved expressions, and zero attribution PnL. The separate accelerated
flip shadow is not empty: its latest report had 907 samples and 894 completed,
but the cost-adjusted time buckets were not promotion ready. Infrastructure
completion and sample volume are not proof of edge.

Verification after implementation:

- focused SPY shadow lifecycle tests: `25 passed`;
- focused options/evidence/safety suites: `190 passed`;
- Python compilation: passed;
- full repository suite: `4,583 passed, 4 skipped` in 251.07 seconds;
- orders submitted: zero;
- execution, sizing, and promotion authority changed: no.

## No-Trade Evidence Throughput Repair 2026-08-11

The month-long collection problem was not one missing entry threshold. It was
three operational defects: latest-decision JSON files overwrote prior failures,
the iron-condor task ran one hour outside its entry window, and the SPY spread
builders abandoned the observation after one unpriceable target-delta pair.

Codex repaired the loop without relaxing a production gate:

- `scripts/options_observation_journal.py` is an append-only, idempotent journal
  for eligible, blocked, skipped, and monitor decisions. Its report separates
  schedule blockers, data blockers, concrete setups, and executable candidates.
- Today was backfilled as four honest observations: three blocked and one
  skipped. Two were schedule-window failures and one was an unpriceable spread.
- SPY 0DTE PM and iron-condor builders now fetch one chain snapshot, rank the
  10-22 delta candidates by distance to target, and select the first exact-width
  pair with valid executable bid/ask math instead of failing on one strike.
- Quote-complete setups that fail production gates are recorded as
  `counterfactual_shadow`; they feed matched evidence but cannot become open
  strategy state. Data-integrity failures still fail closed.
- Seven limited Windows tasks were registered at correct Central times. The PM
  entry observes at 11:05 and 12:05 CT; the state guard prevents duplicate open
  shadow positions while the later run provides a second quote opportunity.
- A separate iron-condor observation task runs Tuesday-Friday at 08:50 CT.
  `--observe-only` converts even fully eligible candidates to counterfactual
  status and cannot create open state or a position ledger entry. Monday's
  production-shadow cadence remains unchanged.
- Schedule governance now passes `70/70`, with zero issues and zero warnings.
- The options shadow runner refreshes the observation report with the matched
  evidence, volatility-premium, and attribution reports.

Safety remains explicit: all new records have `execution_enabled: false`,
`can_submit_orders: false`, and `orders_submitted: 0`. No broker order path was
added or invoked.

## Remaining Work Order For Claude Code

1. Read this handoff and the existing OPRA protocol before editing.
2. Preserve the completed evidence factory, attribution report, executable
   spread math, and fail-closed monitor lifecycle.
3. Build `research/options_exit_policy_lab.py` from resolved OPRA paths before
   changing any exit rule.
4. Build `research/options_limit_execution_lab.py` before changing any limit
   ladder or fill assumption.
5. Create the feature authority registry and run chronological ablations;
   unproven features remain research-only.
6. Keep the nightly Databento acquisition candidate-scoped and cost capped.
7. Collect at least 30 resolved outcomes per strategy across 20 dates before
   an initial diagnostic review.
8. Report exact candidate counts, date counts, quote coverage, unavailable
   reasons, estimated data cost, and tests on every review.
9. Leave all broker execution, sizing, and promotion authority disabled.

## Do Not Spend Time On These Yet

- another candlestick, RSI, FVG, GEX, or market-structure indicator;
- neural networks or LLM trade decisions before clean labels exist;
- copy-trading social-media screenshots;
- tuning thresholds from three shadow outcomes;
- full-chain one-second OPRA history across years;
- naked options, martingale sizing, or daily income targets;
- changing the live/paper strategy because one day reached an all-time high;
- optimizing reported win rate without expectancy and drawdown.

## Files Changed By Codex In This Handoff

- `scripts/options_evidence_factory.py`
- `scripts/options_edge_attribution_report.py`
- `scripts/options_shadow_twin.py`
- `strategies/iwm_options_bot.py`
- `strategies/spy_0dte_pm_spread.py`
- `strategies/spy_iron_condor.py`
- `strategies/spy_theta_harvester.py`
- `research/options_nbbo_curriculum.py`
- `scripts/run_options_shadow_twin.ps1`
- `scripts/run_databento_options_nbbo_curriculum.ps1`
- `scripts/run_spy_0dte_pm_monitor.ps1`
- `scripts/run_spy_iron_condor_monitor.ps1`
- `scripts/options_observation_journal.py`
- `scripts/register_spy_options_observation_tasks.ps1`
- `scripts/run_spy_iron_condor_observation.ps1`
- `scripts/market_schedule_alignment.py`
- corresponding tests under `agent/tests/`
- this handoff

The worktree contains many unrelated modified and untracked research/log files.
Do not revert, stage, or commit them as part of this handoff.

## Paste-Ready Prompt For Claude Code

Read `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_EDGE_PROFITABILITY_RESEARCH_2026-08-11.md`
and execute only the Remaining Work Order. The matched evidence factory,
attribution report, OPRA wiring, executable spread math, and shadow lifecycle
hardening are complete and fully tested. Start with the preregistered exit
policy lab, then the limit-execution lab, then feature authority and ablation.
Preserve every safety boundary, keep execution disabled, do not change sizing
or strategy thresholds, and do not add more indicators. Report exact evidence
coverage and costs. Do not claim profitability until the frozen review
standards pass.
