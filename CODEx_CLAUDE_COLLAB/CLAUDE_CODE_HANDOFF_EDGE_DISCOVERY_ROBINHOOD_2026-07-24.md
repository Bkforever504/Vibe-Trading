# Claude Code Handoff: Find the Missing Edge and Harden the Self-Improving Bots

Date: 2026-07-24
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Branch: `main`
Latest relevant commit: `6eedb61 Validate MES signed-flow absorption data`

## Kenny's Ultimate Goal

Build an automated, survival-first trading system that can:

1. discover a repeatable edge from causal, point-in-time evidence;
2. trade only strategies that remain profitable after realistic spread,
   slippage, commission, tax-lot, settlement, and account-size constraints;
3. learn from every completed, skipped, blocked, and counterfactual trade
   without repeating mistakes;
4. scale from a $1,000 account only after forward evidence supports scaling;
5. eventually use larger or prop-firm capital without changing the research
   standard or bypassing risk controls.

The target is not a manufactured daily win rate. The target is positive
expectancy, controlled drawdown, account survival, and a process that becomes
better calibrated over time. A $1,000 account cannot honestly promise
$100-$200 every day without ruin-level risk. Prove the edge first, then scale
capital.

## Non-Negotiable Boundaries

- Do not enable live trading.
- Do not place, preview, cancel, or modify any Robinhood, Alpaca, NinjaTrader,
  Topstep, Kalshi, or other broker order.
- Do not enable `VibeTradingNinjaTraderMESSim`; it is intentionally disabled.
- Do not alter risk limits, kill switches, mandate files, or manual reset files.
- Do not retune a strategy on a consumed final/OOS period.
- Do not let the learning loop mutate champion parameters or promote itself.
- Do not spend Databento credits or incur any subscription/API charge.
- Do not clean or revert the dirty worktree. Many background scheduled tasks
  append to tracked logs. Stage and commit only files you intentionally change.
- Respect `STATUS.md`: one active task at a time.

## Current System Truth

### Overall readiness

Latest `elite_bot_readiness_scorecard_log.jsonl`:

- overall score: 5.6/10;
- risk controls: verified 10/10;
- learning loop: 8/10, evidence-capped;
- entry quality: 7/10, only 12 post-hardening closed trades;
- research validity: 6/10, immutable trial ledger currently sees only 1 trial;
- exit quality: 4/10, only 2 complete forward paths;
- proven profitability: 4/10, only 12 post-hardening trades and 26 days;
- operational integrity: 2/10 because one signal-stack output is stale and
  schedule alignment is not fully clean;
- no component has order authority.

The attractive aggregate paper numbers (`$2,332`, expectancy `$194.33`, PF
`4.95`) are too small and heterogeneous to call proven profitability.

Latest verifier state:

- 64 instruments inspected;
- 64 blocked;
- 0 promotion-ready;
- governance not passed.

### What has genuinely succeeded

#### 1. ETF momentum rotation: strongest current lane

Frozen rule:

- universe: SPY, QQQ, GLD, XLE, TLT, IWM, XLK, XLV, XLF, XLI;
- 12-month lookback;
- top two ETFs;
- five-trading-day rebalance;
- next-bar position shift;
- cash behavior preserved exactly.

Consumed 2025+ evidence through 2026-07-17:

- return: +51.08%;
- profit factor: 3.456;
- Sharpe: 1.572;
- max drawdown: 12.20%;
- 23 trades;
- win rate: 69.6%;
- doubled switching cost result: +49.01%.

Safer half-deployed study:

- return: +21.25%;
- max drawdown: 6.67%;
- doubled-cost return: +20.56%.

Current clean forward tracker:

- canonical position entered 2026-07-21: XLE + XLK;
- this position is eligible for the new forward gate;
- no eligible clean tracker exit is resolved yet;
- the earlier XLK + IWM result was explicitly invalidated/diagnostic because
  the tracker rebalance phase did not match the frozen backtest.

Do not merge the 23 consumed historical-forward trades with the clean tracker
count. Do not change the frozen parameters.

#### 2. SPY turn-of-month: historically passed, small overlay

Frozen rule: long SPY from the close of the fifth-to-last trading day through
the close of the third trading day of the next month.

- positive in all three 2000-2015 development regimes;
- 2016-2020 selection: +63.6%, PF 1.40, max DD 8.8%;
- 2021+ final: +19.3%, PF 1.12, max DD 15.6%;
- remained positive at 2x and 3x costs.

This edge is weakening and widely known. On $1,000, recent expected
contribution is only about $40-$50 per year. It is useful as a low-exposure
overlay, not an income engine.

#### 3. PEAD proxy: promising but not deployment-grade

Frozen price-reaction proxy: 30 megacaps, reaction day >= +3%, hold 20 days.

- 1,182 development events: +7.35% mean/event, 80.9% WR, PF 14.2;
- 788 test events: +5.98% mean/event, 78.2% WR, PF 6.2;
- unconditional 20-day control: +1.71%;
- approximate excess in test: +4.3% per event.

Caveats are material: today-selected universe, shallow free-data history,
overlapping exposures, crude earnings-surprise proxy, and possible revision
bias in yfinance earnings dates. It needs point-in-time earnings data and
portfolio-level exposure accounting.

#### 4. Engineering and safety infrastructure

- broker-neutral live mandate and fail-closed enforcement;
- append-only learning/mistake logs;
- adversarial manifests;
- champion/challenger separation;
- no automatic promotion;
- scheduled shadow scanners and forward trackers;
- explicit market-calendar, risk, concentration, and kill-switch layers;
- realistic bid/ask requirements in the newer options evidence path;
- consumed-dataset and preregistration discipline is now established.

### What has failed and must not be revived by retuning

- SPY/QQQ/IWM ORB variants under realistic costs;
- MES ORB and pullback families;
- MES liquidity-sweep fade;
- MES FVG continuation;
- MES VWAP-band fade;
- MES close momentum/reversal;
- MES overnight and opening-pressure hypotheses;
- MES top-of-book quote imbalance continuation/reversal;
- MES signed-flow absorption rule frozen on 2025 Q4: zero candidate windows;
- unconditional SPY/QQQ overnight drift;
- pre-FOMC drift in the recent final period;
- QQQ turn-of-month;
- many Pine/indicator combinations including KAMA, EMA, and social-media
  systems that failed regime/OOS gates.

Read:

- `research/NEXT_EDGE_TESTS_RESULTS_2026-07-19.md`
- `research/MES_SIGNED_FLOW_ABSORPTION_RESULTS_2026-07-21.md`
- `research/MES_SIGNED_FLOW_FORWARD_PROTOCOL_2026-07-21.md`
- `research/LIQUID_MARKET_EDGE_CONFIDENCE_2026-07-19.md`

## Robinhood API Status: Important Nuance

Codex successfully called the Robinhood MCP `get_accounts` tool on 2026-07-24.
The remote API/OAuth layer is therefore alive in the Codex environment.

Observed accounts, masked:

- default individual margin account ending `7640`: active, option level 2,
  but `agentic_allowed=false` for this agent;
- nickname `Agentic`, individual cash account ending `8540`: active and
  `agentic_allowed=true`, but currently has no options permission.

Do not store full account numbers in the repo, logs, tests, or handoff updates.

The repository-local CLI is not yet connected:

```text
Trading Connector: robinhood-live-mcp
Configured: no
OAuth token: missing
Status: not_authorized
```

This means "Robinhood API works in Codex" is not the same as "the local
Vibe-Trading runner is configured." Preserve that distinction.

## Major Improvement Work

### P0-A: Fix operational truth before adding strategy logic

Current `STATUS.md` reports 61 healthy outputs and 1 stale output. Schedule
alignment reports one issue because the alignment task observed itself in a
Running state. Diagnose these as plumbing/observation issues first.

Requirements:

1. identify the exact stale output and its producer;
2. determine whether it is a real missed run, timestamp parsing error, or
   self-observation race;
3. fix only task/log/report plumbing;
4. make schedule evaluation treat its own currently-running state correctly
   without hiding genuinely stuck tasks;
5. do not change any trading or risk behavior.

Success:

- 0 stale/missing/error outputs;
- schedule alignment passes;
- required execution tasks remain unchanged;
- MES task remains disabled.

### P0-B: Repair the learning loop's attribution errors

The latest learning report has 181 mistake events, 27 repeated patterns, 5
critical unresolved patterns, and 6 challenger nominations. However, several
clusters reveal taxonomy bugs:

- bearish puts judged by bullish-direction rules;
- bullish calls judged by bearish-direction rules;
- long options judged by credit-spread stop rules;
- many records have `entry_pattern=unknown`,
  `trend_alignment=unconfirmed`, `expected_move_bucket=unknown`, or missing
  regime context.

This is likely the highest-value current defect. A learner trained on mislabeled
mistakes will confidently learn the wrong lesson.

Build:

1. a canonical `strategy_family`, `instrument_type`, `position_structure`,
   `right`, `direction`, and `exit_policy` taxonomy;
2. strategy/right-aware postmortem rules;
3. schema validation that rejects incompatible rule application;
4. end-to-end `signal_id` linking across proposal, entry, quote path, exit,
   postmortem, mistake ledger, challenger, and trial result;
5. explicit `unknown_reason` fields rather than silently grouping unknowns;
6. source/provenance and point-in-time timestamps for every feature;
7. tests proving calls, puts, debit trades, credit spreads, equities, and
   futures cannot be graded by each other's rules.

Do not rewrite old append-only logs. Add a versioned derived normalization
layer and mark invalid historical lessons as excluded from challenger support.

Success:

- zero incompatible-rule classifications in a replay audit;
- at least 95% of new closed-trade records have complete core telemetry;
- challenger support counts are recomputed from valid, compatible evidence;
- champion configs are unchanged.

### P0-C: Make the experiment ledger honest and exhaustive

The project has tested at least 13 strategy families, but the readiness report
sees only 1 immutable attempted edge trial. That breaks multiple-testing
awareness and overstates confidence.

Build an immutable experiment registry that records:

- preregistration path and SHA-256;
- code commit;
- strategy family and hypothesis;
- exact data source and date ranges;
- consumed development/selection/final partitions;
- parameter count and number of alternatives searched;
- base and stressed costs;
- pass/fail stage and reason;
- whether final data was opened;
- result artifact hash;
- promotion authority (always human-only).

Backfill only trials with verifiable preregistration/result artifacts. Do not
invent metadata. Label incomplete historical trials as `legacy_incomplete`.

Add:

- duplicate-dataset/final-period detection;
- family-level trial counts;
- PBO/deflated-Sharpe or an explicit multiple-testing penalty where sample
  size permits;
- an outlier-removal stress test;
- parameter-neighborhood stability;
- a decay report comparing older and newer regimes.

### P0-D: Verify Robinhood read-only connectivity inside the repo

Use the repo's canonical seed in `agent/src/config/schema.py`.

First deliverable is read-only only:

- account discovery;
- portfolio/buying-power read;
- positions read;
- open/recent orders read;
- quote read for SPY and the current XLE/XLK momentum holdings;
- redacted audit log;
- deterministic failure when OAuth expires.

Do not request wildcard or write scopes. Do not add `place_order` or
`cancel_order`. Do not copy OAuth tokens into `.env`, tracked config, logs, or
tests.

If the Robinhood tool catalog differs from the repo's canonical names, update
classification tests from observed read-only metadata, default-deny unknown
tools, and document the discrepancy. Do not broaden permissions to make the
test pass.

Use only the agent-accessible cash account ending `8540` for read canaries.
The account has no options permission, so Robinhood options execution is
currently unavailable even if read connectivity succeeds.

### P1-A: Independently replicate the strongest edge

Replicate frozen ETF momentum without changing parameters using:

1. Alpaca daily bars;
2. Robinhood read quotes/current holdings where available;
3. yfinance only as the existing comparison.

Audit:

- adjusted vs unadjusted prices;
- distributions/splits;
- exact rebalance phase;
- next-bar fill timing;
- fractional-share feasibility;
- spread and switching costs;
- missing-bar/calendar differences;
- cash settlement and buying-power constraints in a $1,000 cash account.

Produce a daily signal parity report and a trade-by-trade disagreement report.
Do not call disagreement a new edge; resolve its data cause.

### P1-B: Replace the PEAD proxy with point-in-time event evidence

The PEAD result is the best genuinely orthogonal candidate, but the current
event source is not sufficient.

Build a provider-neutral event schema:

- scheduled earnings timestamp known before the event;
- actual release timestamp;
- actual EPS, consensus EPS, standardized surprise where licensed;
- guidance/revision fields when available;
- reaction-day open/close definition;
- no revised future calendar data leaking backward;
- overlapping-position and sector concentration accounting.

Preregister one exact long-only PEAD rule before opening new outcomes.
Compare it with the unconditional same-symbol/same-period control and the
momentum lane's exposure.

No paid data purchase without Kenny's separate approval.

### P1-C: Turn the learning loop into a causal challenger factory

The loop must learn, but it must not chase recent P&L.

For each valid completed or skipped signal, record:

- what the bot knew at decision time;
- thesis and expected mechanism;
- executable entry/exit quotes;
- maximum favorable/adverse excursion;
- spread, IV, theta, and volatility-regime attribution where applicable;
- market/sector beta contribution;
- whether failure came from entry, direction, timing, sizing, exit, liquidity,
  event risk, or data quality;
- a matched counterfactual (same setup without the proposed change).

Challenger lifecycle:

1. detect a repeated compatible failure cluster;
2. propose one minimal rule change;
3. freeze hypothesis, code, data boundary, and expected mechanism;
4. run shadow-only beside the unchanged champion;
5. require at least 30 resolved outcomes and 20 trading days;
6. evaluate base/stressed expectancy, drawdown, calibration, and regime
   stability;
7. run independent adversarial review;
8. allow human promotion review only.

The loop may update beliefs and rank challengers. It may never mutate
production parameters, increase risk, or grant itself order authority.

### P1-D: Reduce scanner noise

The stack has more than 60 scheduled analytical outputs. More indicators do
not automatically mean more edge.

Build a scanner utility report:

- unique incremental information versus the frozen champion;
- forward coverage and freshness;
- signal overlap/correlation;
- calibration and realized lift;
- false-positive burden;
- operational cost and failure rate;
- whether any downstream decision actually consumes the output.

Mark redundant/unconsumed scanners as retirement candidates, but do not delete
or disable them in this task. The goal is a smaller, better-instrumented
toolbox.

### P1-E: Portfolio-level edge, not isolated screenshots

Test the passing lanes as a constrained portfolio:

- full and 50%-deployed momentum;
- SPY turn-of-month overlay;
- PEAD only after point-in-time repair;
- cash as an explicit allocation;
- no options premium until executable lifecycle evidence exists.

Measure:

- CAGR and dollar return on $1,000;
- max drawdown and time under water;
- turnover and realistic costs;
- worst month and rolling 12-month result;
- concentration and simultaneous exposure;
- marginal contribution and correlation of each lane;
- probability of account falling below survival thresholds.

Use rolling walk-forward evaluation. No weights may be selected on the final
period.

### P2: Keep MES future-only

Do not search the consumed MES datasets again.

The next MES work is only the frozen forward protocol:

- collect 30 new outcome-blind sessions;
- measure joint signed-flow/price-response density;
- freeze at most one feasible challenger;
- evaluate on 30 still-later Sim101 trades;
- require PF >= 1.30, positive stressed expectancy, max DD <= $200, zero prop
  violations, and no single trade >25% of net profit.

No Topstep purchase and no Databento purchase in this task.

## Suggested First Implementation Sequence

1. Read `STATUS.md`, this handoff, and the four result/protocol documents.
2. Fix the one stale output and self-observation schedule race.
3. Write findings for the incompatible learning labels before changing code.
4. Add versioned taxonomy, schema validation, and focused tests.
5. Rebuild challenger support using only compatible evidence.
6. Build/backfill the immutable trial registry from verifiable artifacts.
7. Verify Robinhood read-only connectivity and redact all identifiers.
8. Independently replicate frozen momentum with Alpaca/Robinhood data.
9. Return an updated readiness score based on evidence, not aspiration.

## Required Tests

At minimum, add focused tests for:

- calls/puts and long/credit structures use the correct postmortem rules;
- incompatible strategy rules fail closed;
- signal IDs join the complete lifecycle without collisions;
- missing point-in-time fields cannot become promotion evidence;
- consumed final periods cannot be reopened under a renamed strategy;
- experiment artifacts and preregistration hashes are immutable;
- Robinhood unknown tools default-deny;
- Robinhood account identifiers and OAuth material are redacted;
- read-only OAuth cannot invoke write tools;
- momentum parity across providers preserves the frozen rebalance phase;
- scheduled-health self-observation does not create a false failure;
- MES execution remains disabled.

## Definition of Success for This Handoff

Claude should return:

1. severity-ordered findings;
2. exact files changed;
3. exact tests and commands run;
4. before/after operational and evidence scores;
5. a Robinhood read-only connectivity verdict;
6. a corrected learning-cluster report;
7. an immutable trial-registry report;
8. independent momentum parity results;
9. remaining blockers and honest confidence by category.

No result from this handoff permits live trading. The best possible outcome is
a cleaner causal learning system, trustworthy broker data, and one or more
forward candidates that deserve continued observation.
