# Public SPY/SPX Strategy Replication Preregistration

Date frozen: 2026-08-08

Scope: publicly attributed SPY, SPX, and XSP strategies

Authority: research and forward shadow only

## Research Question

Can a fully specified public strategy retain positive executable expectancy
after source delay, OPRA bid/ask friction, fees, additional slippage, outlier
removal, chronological holdout, and regime partitioning?

Screenshots, testimonials, PnL claims, post-entry alerts, and reconstructed
entries selected after the result are known cannot answer this question.

## Frozen Unit Of Analysis

The primary cohort is one immutable `rule_id + version + rule_hash`. A change to
an entry predicate, contract-selection rule, stop, target, time exit, no-trade
condition, regime filter, or position-sizing rule requires a new version. A
registered version cannot be overwritten.

Each rule must specify:

- attributed source traders
- eligible SPY-family instruments
- Eastern Time entry windows
- machine-readable entry predicates
- deterministic OPRA contract selection
- limit-only entry policy with no market fallback
- stop, target, and time-exit policies
- no-trade conditions and regime filters
- maximum account risk no greater than 1%

## Source Evidence

Signals first pass through `scripts/verified_trader_intake.py`. Replication
snapshots accept only non-quarantined, replay-eligible signal events whose
source timestamp is no later than the observation timestamp. The source trader
and instrument must match the frozen rule.

Complete source coverage requires a manifest containing the captured period,
source identity, poll interval, captured count, deletion tracking, and SHA-256
of the archive. Coverage that does not attest both complete capture and deletion
tracking fails closed.

## Tamper Evidence

`data/public_strategy_replication_log.jsonl` is append-only and hash chained.
Every event stores its sequence number, the prior event hash, and its own hash.
Any historical edit, removal, insertion, reorder, or event-ID collision causes
verification to fail before a report is built.

This is tamper-evident, not a claim that a local administrator cannot replace
the complete file and its external backups. Operational deployment should
publish each daily head hash to a separately controlled archive.

## Executable Reconstruction

Resolved outcomes must reference a captured signal and its exact frozen rule
hash. The reconstruction must provide:

- exact option instrument
- OPRA as quote authority
- point-in-time entry quote no more than the rule's maximum quote age after the
  signal was observed
- later exit quote
- aggregate executable entry and exit values
- corresponding midpoint values
- quantity, multiplier, capital at risk, fees, and additional slippage
- market regime and resolution reason

The pipeline computes gross PnL, round-trip spread friction, net PnL, net R,
and doubled-cost R. Source-reported PnL is not accepted into those calculations.

## Fixed Nomination Gates

A cohort becomes a `forward_shadow_nominee` only when all conditions pass:

- at least 30 pre-entry signals
- at least 30 independently reconstructed outcomes
- at least 20 distinct resolved dates
- at least 95% source-manifest coverage
- at least 80% valid point-in-time market joins
- at least 80% outcome reconstruction rate
- positive one-sided 95% executable expectancy lower bound
- chronological final-25% holdout containing at least 10 outcomes
- positive holdout executable expectancy lower bound
- profit factor at least 1.20
- positive expectancy under doubled costs
- positive expectancy after removing the best 1% and best 5% of outcomes
- maximum cumulative drawdown no greater than 10R
- at least two regimes with five or more outcomes and positive mean R

These are nomination gates only. The report permanently emits:

- `execution_enabled: false`
- `can_submit_orders: false`
- `paper_gate_ready: false`
- `automatic_promotion: false`

Independent adversarial review and explicit human approval remain mandatory
before any separate forward-paper proposal. Production authority is out of
scope.

## Stopping Rule

Do not retune a failing rule in place. Close the version, document its result,
and preregister a new version. Do not remove losses, failed fills, stale joins,
or unfilled calls from the denominator.

No profitability claim is authorized by this implementation.
