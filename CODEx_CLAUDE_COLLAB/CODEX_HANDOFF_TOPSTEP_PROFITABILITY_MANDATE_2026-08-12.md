# Codex Handoff: Topstep Profitability Mandate - 2026-08-12

## Mission

Build the best defensible path to profitable Topstep trading with MES on
TopstepX. Profitability is the objective, not an assumption or a promise.
Claude must improve the probability of durable net profitability while obeying
Topstep rules, preserving capital, and refusing to manufacture performance by
overfitting, leverage, simulator exploitation, or selective reporting.

The fastest valid route is:

1. stop re-testing candle families that have already failed;
2. make the ProjectX market-data lane operational on this personal device;
3. collect genuinely new quote, trade, and depth information;
4. freeze one small microstructure hypothesis family before opening outcomes;
5. require realistic costs, chronological forward evidence, and exact Topstep
   risk simulation;
6. promote only through shadow and Practice, one MES at a time.

No order was submitted while preparing this handoff.

## Non-Negotiable Truth

There is no guaranteed strategy, guaranteed daily income, or valid way to force
the market to pay a dollar target. A profitable bot must show positive
expectancy after costs on unseen data and survive Topstep's path-dependent
Maximum Loss Limit. Win rate alone is not an edge.

"By any means" does not authorize prohibited or irresponsible conduct. Never:

- exploit simulated fills, stale prices, feed delays, or platform errors;
- trade outside the best bid or offer;
- use account stacking, cross-account hedging, coordinated trades, or multiple
  profiles;
- use a VPN, VPS, cloud runner, or remote server for TopstepX API activity;
- run high-speed or mass-order tactics intended to exploit the simulator;
- trade maximum size into scheduled major news;
- share credentials, trade on another person's behalf, or evade restrictions;
- martingale, average down, widen stops after entry, or scale an unproven edge;
- purchase a Combine, Reset, API plan, or data product without explicit user
  authorization.

## Current Official Topstep Rules Snapshot

Verified from official Topstep Help Center pages on 2026-08-12. Re-verify these
before any account activation because rules can change.

For a 50K Trading Combine:

- profit target: $3,000;
- Maximum Loss Limit: $2,000, trailing at end of day and monitored against
  real-time realized plus unrealized P&L;
- consistency target: best day must remain at or below 50% of total profit, or
  the effective target increases;
- maximum position: 5 minis or 50 micros, but this project is capped at 1 MES;
- automation is permitted subject to Topstep's conduct and strategy rules;
- TopstepX API access has no sandbox and is billed separately;
- API activity must originate from the user's personal device; VPN, VPS, and
  remote-server use is prohibited.

Authoritative sources:

- https://help.topstep.com/en/articles/8284197-trading-combine-parameters
- https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit
- https://help.topstep.com/en/articles/8284208-consistency-at-topstep
- https://help.topstep.com/en/articles/11187768-topstepx-api-access
- https://help.topstep.com/en/articles/10296582-prohibited-conduct
- https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep

The repository's rule snapshot and simulator must be compared with these pages.
If they disagree, execution stays disabled until the local rules and tests are
updated.

## Current Local State

Repository:

`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

The worktree is heavily dirty with unrelated user, agent, generated research,
and log changes. Do not reset, clean, discard, or overwrite them. Scope edits
to Topstep research, adapters, tests, rules, and handoffs.

Topstep environment presence checked on 2026-08-12 without printing values:

- `TOPSTEPX_USERNAME`: absent
- `TOPSTEPX_API_KEY`: absent
- `TOPSTEPX_PRACTICE_ACCOUNT_ID`: absent
- `TOPSTEPX_LOCAL_DEVICE`: absent
- `TOPSTEPX_PRACTICE_EXECUTION`: absent

Scheduled-task state:

- `VibeTradingNinjaTraderMESSim`: disabled
- no TopstepX recorder or execution task is installed

Keep both conditions fail closed. Missing credentials block activation, not
offline research and tests. Never print an API key or write it to a report.

## Evidence Already Obtained

### Current-Regime ORB and Pullback Search

Source:

- `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_TOPSTEP_CURRENT_REGIME_2026-08-10.md`
- `data/mes_strategy_search_2024plus_rollsafe_unique_diagnostic.json`

Result:

- 2024-01-02 through 2026-07-17;
- 16,320 executable candidates;
- 58 development survivors but only 33 unique trade paths;
- zero selection survivors;
- least-negative selection row: -$1.77 base expectancy and -$5.95 with doubled
  costs.

Decision: rejected. Do not widen, rerun, or relabel this grid as new evidence.

### Opening-Gap Fade

Sources:

- `research/MES_OPENING_GAP_FADE_PREREGISTRATION_2026-08-09.md`
- `research/MES_OPENING_GAP_FADE_RESULTS_2026-08-09.md`
- `data/mes_opening_gap_fade_results.json`

Result: 12 frozen variants, zero stability survivors, 0% simulated Combine pass
rate at 1-2 MES. Rejected. Do not optimize the same dates after observing this
result.

### Public Strategy Replication and BBO/OFI

Sources:

- `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_PUBLIC_STRATEGY_REPLICATION_2026-08-10.md`
- `data/mes_public_strategy_replication_results.json`
- `research/MES_CAUSAL_IMPACT_REVERSAL_RESULTS_2026-08-10.md`

Result: no public ORB/FVG/VWAP-style replica or BBO/OFI causal-impact candidate
survived realistic transaction costs. The best ORB gross expectancy was
consumed by friction. BBO snapshots cannot identify queue replenishment,
cancellations, or hidden liquidity well enough to support an absorption claim.

Decision: rejected as an execution strategy. BBO remains useful for spread and
fill-quality measurements.

### Signed-Flow Absorption Attempt

Sources:

- `research/MES_SIGNED_FLOW_ABSORPTION_PHASE_B_2026-07-21.md`
- `research/MES_SIGNED_FLOW_ABSORPTION_RESULTS_2026-07-21.md`

The 61-session Databento trade-print dataset passed quality checks, but the
frozen one-minute conjunction produced zero candidates. Outcomes were not
opened. The exact rule is infeasible and rejected. Its thresholds may not be
loosened on that consumed period.

### Combine Simulation

Source: `data/topstep_combine_simulation.json`

The current ORB candidate has near-zero gross edge and negative stressed edge.
Scaling contracts increases Maximum Loss Limit failures; it does not create
expectancy. Do not buy a Combine for this candidate.

## Data Inventory and Evidence Labels

Existing local data includes:

- `data/databento/mes_bbo_ofi_30s_2024_2026.parquet`
- `data/databento/mes_bbo_valid_1s_2024_2026.parquet`
- `data/databento/mes_signed_flow_windows_2025q4.parquet`
- `data/databento/mes_v0_trades_2025q4.parquet`

These datasets are useful for parser, feature, latency, cost, and feasibility
tests. They are consumed history and cannot provide untouched validation for a
new strategy.

The new-information lane is:

- `strategies/topstepx_market_recorder.py`
- `scripts/topstepx_market_recorder.py`
- `research/topstepx_microstructure_features.py`
- `research/TOPSTEPX_MICROSTRUCTURE_DATA_PROTOCOL_2026-08-09.md`

It records quotes, aggressor trades, and explicit depth updates with source and
local receipt timestamps. It is read only and contains no account or order
methods.

## Primary Research Direction

The next hypothesis must use information not present in one-minute OHLCV:
signed aggressive flow, price impact, top-five depth, replenishment, spread
state, and event timing.

Start with one absorption/reversal family only. Do not test continuation on the
same forward outcome period unless both families are preregistered together and
the multiple-testing correction is frozen in advance.

Conceptual mechanism:

1. unusually one-sided aggressive flow arrives;
2. same-direction price impact is weak relative to that flow;
3. opposing depth persists or replenishes rather than depletes;
4. the spread recovers and price crosses back through the event midpoint;
5. the bot enters opposite the aggressive flow after a one-update delay.

This is a hypothesis, not an edge. Thresholds must come from outcome-blind
feature distributions and be frozen before future P&L is opened.

The small preregistered family may contain at most four neighboring variants.
Freeze all of the following:

- event-bucket duration;
- aggressive-volume and imbalance definitions;
- price-impact normalization;
- depth persistence or replenishment definition;
- spread/depletion veto;
- confirmation and one-update delay;
- 09:45-11:30 ET entry window;
- economic-event exclusions known before entry;
- one entry per session;
- 1 MES only;
- executable side of BBO for every entry and exit;
- commission, exchange fees, and slippage stress;
- structural stop between 12 and 40 ticks;
- target no greater than 80 ticks and expressed in R;
- maximum holding time and end-of-window flatten;
- familywise alpha and all promotion gates;
- source-code and preregistration hashes.

Do not choose a requested win rate. Optimize for net expectancy, drawdown, and
survival after costs. A lower-win-rate strategy can be superior when its payoff
ratio is better.

## Collection Gate

Enforce the existing protocol before opening strategy outcomes:

- at least 20 complete RTH sessions;
- at least 50,000 quote, 50,000 trade, and 50,000 depth events;
- at least 95% of active five-second windows contain all three event types;
- p99 local receipt minus source timestamp below one second;
- no unresolved reconnect gap over ten seconds during 09:30-11:30 ET;
- active MES contract and tick specification verified daily;
- event-day labels recorded before analysis.

If this fails, repair collection. Do not replace missing depth with synthetic
depth, candle indicators, or social-media levels.

## Evaluation Standard

All reports must include no-trade sessions and separate gross edge from costs.
Use observed spread, $2.48 round-trip commission unless a newer verified fee is
available, one adverse tick per side in base stress, and two adverse ticks per
side plus doubled commission in severe stress.

Use chronological development, selection, and untouched forward periods. Apply
session-level block bootstrap and exact Topstep path simulation. Report at
least:

- sessions, eligible events, signals, trades, and no-trade days;
- win rate with confidence interval;
- average win, average loss, payoff ratio, and break-even win rate;
- gross and net expectancy per trade and per session;
- profit factor and Sortino ratio;
- maximum drawdown and maximum adverse excursion;
- median and p95 slippage;
- best-day concentration and Topstep consistency impact;
- Combine pass, MLL failure, and incomplete probabilities;
- neighboring-parameter stability and event/regime breakdowns;
- base, doubled-cost, delayed-entry, and worst-fill stress results.

A family may advance from historical research only if all frozen gates pass:

- at least 30 development trades and 20 selection trades;
- positive net expectancy and profit factor at least 1.20 in development and
  selection;
- positive expectancy and profit factor at least 1.10 under doubled costs;
- no single day contributes more than 30% of total net profit;
- maximum historical drawdown no greater than $500 at 1 MES;
- no material collapse in adjacent parameters, weekdays, or volatility states;
- familywise significance or a clearly labeled inconclusive result;
- no rule, data-quality, timestamp, or execution-integrity violation.

Historical advancement is not Practice authorization. Promotion still requires
at least 30 later, untouched chronological shadow outcomes under frozen code.
Practice advancement then requires at least 30 completed 1-MES Practice trades,
positive stressed expectancy, zero rule violations, zero duplicate entries,
and reliable bracket/flatten behavior.

Before recommending a Combine purchase, require the exact frozen Practice P&L
path to show, under 5,000 session-block bootstraps:

- at least 60% probability of passing within 252 sessions;
- at most 5% probability of hitting the MLL;
- positive severe-stress expectancy;
- no dependence on increasing beyond 1 MES;
- estimated fees and subscription cost included in economic expectancy.

If these thresholds are not met, the honest output is `not_ready`, not a larger
position or another optimized backtest.

## Execution and Risk Architecture

Preserve `strategies/topstepx_practice_adapter.py` as Practice-only. It already
requires:

- an exact account ID allowlist;
- an API-returned account name containing the standalone `PRACTICE` marker;
- `PRACTICE_ONLY_CONFIRMED`;
- `PERSONAL_DEVICE_CONFIRMED`;
- at most 1 MES;
- 09:45-11:30 ET entries;
- stop no greater than 40 ticks and target no greater than 80 ticks;
- no existing position/order and no prior session entry;
- deterministic prop-rule approval and an emergency block file.

Do not add a Combine or funded override. A later adapter must be a separate,
explicitly reviewed module after the promotion ladder passes and the user gives
written authorization.

For any future Practice order path, require:

- client-generated idempotency key persisted before submission;
- no automatic retry after an ambiguous order response;
- broker reconciliation before every new entry;
- server-confirmed bracket protection immediately after fill;
- fail-closed behavior on stale quotes, missing depth, disconnect, rule-state
  ambiguity, news-calendar failure, or position mismatch;
- personal daily loss lock of $100 and daily profit lock chosen below the
  Topstep consistency ceiling;
- one entry per session and no averaging down;
- alert plus manual reset after any crash or reconciliation failure.

## Claude Code Work Order

Execute in this order. Do not stop at a strategy description.

1. Read this handoff and every source named above. Audit current Topstep diffs
   before editing and preserve unrelated worktree changes.
2. Re-verify all six official Topstep pages. Update the versioned JSON rules and
   tests if values or conduct rules changed. Record retrieval timestamps and
   source URLs. Keep execution disabled on any mismatch.
3. Run focused Topstep tests. Fix only reproducible defects in the recorder,
   feature builder, rule gate, simulator, and Practice adapter. Never weaken a
   safety check to make a test pass.
4. Add `scripts/topstep_profitability_readiness_report.py` and focused tests. It
   must aggregate credentials-present booleans, task state, data-quality gates,
   research verdicts, forward sample counts, Practice sample counts, rule
   freshness, and execution authority into one fail-closed JSON report. It must
   never expose credentials.
5. Add a daily TopstepX recorder quality report implementing every collection
   gate in `research/TOPSTEPX_MICROSTRUCTURE_DATA_PROTOCOL_2026-08-09.md`.
   Distinguish absent data from zero events and report reconnect gaps explicitly.
6. Use consumed Databento data only to test parsers, causal feature computation,
   executable fill math, and candidate frequency. Do not use its P&L to claim
   independent validation or retune rejected thresholds.
7. Prepare, but do not activate, a small absorption/reversal experiment. Write a
   dated preregistration with no more than four variants and hash the code and
   config. Do not open outcomes until the new ProjectX collection gate passes.
8. If credentials and a Practice account remain absent, do not ask for secrets
   in chat and do not enable execution. Produce the exact user-side setup steps
   and continue all offline work.
9. If credentials later exist, run the read-only probe and a short manual
   recorder smoke test on the user's personal device. Validate MES contract,
   quote/trade/depth streams, timestamps, reconnects, rotation, and redaction.
   Do not schedule it until the smoke test passes.
10. After the smoke test, install only the read-only recorder task. Leave
    `TOPSTEPX_PRACTICE_EXECUTION` blank. Accumulate and quality-check at least 20
    complete sessions.
11. Once the collection gate passes, freeze the experiment and collect untouched
    shadow evidence. Use the exact evaluation and promotion gates above. Report
    zero survivors plainly if that is the result.
12. Run focused tests, then the full repository suite. Run `git diff --check`.
    Produce a new dated handoff with exact commands, files, test counts,
    evidence labels, blockers, and an explicit statement of whether any order
    was submitted.

## Immediate Deliverables

Claude's next session is successful when it produces:

1. a fresh official-rule snapshot with tests;
2. a machine-readable profitability-readiness report;
3. a complete daily recorder-quality report;
4. a dated, hashed absorption/reversal preregistration;
5. focused and full-suite verification;
6. no orders and no execution enablement.

The goal is not to make the dashboard look profitable. The goal is to discover
whether a repeatable net edge exists, protect the account while finding out,
and promote it only when the evidence can survive costs, unseen data, and
Topstep's actual rules.

## Paste-Ready Claude Code Directive

Continue from
`CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_TOPSTEP_PROFITABILITY_MANDATE_2026-08-12.md`.
Treat it as the controlling Topstep work order. Build the rule snapshot,
profitability-readiness report, recorder-quality report, and the frozen
absorption/reversal experiment scaffold. Preserve the Practice-only adapter and
all fail-closed boundaries. Do not rerun or widen rejected candle grids, expose
credentials, purchase anything, enable Practice execution, submit orders, or
claim profitability without untouched cost-stressed evidence. Run focused and
full tests, then write the next dated handoff with exact results and blockers.
