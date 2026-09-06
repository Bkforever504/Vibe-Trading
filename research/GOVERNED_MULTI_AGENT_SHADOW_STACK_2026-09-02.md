# Governed Multi-Agent Shadow Stack

Date frozen: 2026-09-02

## Decision

Do **not** import a turnkey "AI trading" repository and do not add broker or
order-submission software.  Build a small, owned decision pipeline around the
existing shadow system.  The first implementation should use **PostgreSQL +
Pydantic AI + OpenTelemetry**, with the existing deterministic scheduler and
research scripts.  Add Temporal only when restart-safe, multi-hour workflows
are demonstrably the operational bottleneck.  Use Qlib only as an isolated
research/backtest lab, never as the authority that accepts a trade.

This is deliberately not an LLM-majority-vote system.  A deterministic policy
engine is the only component permitted to label a candidate `shadow_accepted`;
all agents are evidence producers and critics.

## Minimum architecture

```
market snapshot -> immutable decision ledger -> independent evidence cards
                  -> deterministic policy gate -> shadow position / rejection
                  -> resolved outcome -> evaluation and rule-change proposal
```

For every candidate, persist the raw source identifiers/hashes, as-of time,
agent/model/prompt version, independently generated card, dissent, gate result,
simulated fill assumptions, outcome, and code/config fingerprint.  The ledger
is append-only at the application role: corrections are new events that point
to the event they supersede.  No agent receives database write authority beyond
an append procedure; no component imports a brokerage client.

## Candidates evaluated (primary-source review)

| Component | Fits | License / current project signal | Integration risk | Decision |
|---|---|---|---|---|
| [PostgreSQL](https://github.com/postgres/postgres) | Canonical event/decision/outcome ledger; transactions and foreign keys make it suitable for enforcing the event chain. | PostgreSQL License is permissive ([COPYRIGHT](https://raw.githubusercontent.com/postgres/postgres/master/COPYRIGHT)); its source README describes transactions, foreign keys, triggers, and user-defined functions. | It is a database, not event sourcing: schema, append-only permissions, migrations, and backup/restore tests are ours to own. | **Adopt now.** Avoid a second event-store service at this stage. |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | Typed evidence-card schemas, tool input validation, and model-provider abstraction. The README shows declared output types and validated tool arguments. | MIT ([LICENSE](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE)); the repository is active and includes agents, evals, graph, docs, examples, and tests. | LLM output can still be wrong; typed JSON validates shape, not truth. Provider/model changes require frozen prompt/model/version fields and replay fixtures. | **Adopt now** for bounded evidence producers, with no order tools. |
| [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python) | Trace the candidate from data retrieval through each card, gate, and outcome; correlate errors and latency without confusing telemetry with the ledger. | Apache-2.0 ([LICENSE](https://github.com/open-telemetry/opentelemetry-python/blob/main/LICENSE)); upstream marks traces and metrics stable, while logs remain in development. | Cardinality and sensitive-prompt/data leakage: emit IDs/hashes and explicitly redacted fields; retention and exporter selection are operational work. | **Adopt now** for traces/metrics; keep the database as the audit record. |
| [Temporal Python SDK](https://github.com/temporalio/sdk-python) / [server](https://github.com/temporalio/temporal) | Durable orchestration for schedules, retries, approval waits, and recovery after a process failure. Its README describes a distributed, durable orchestration engine and workflow replay/testing. | MIT ([server LICENSE](https://github.com/temporalio/temporal/blob/main/LICENSE)); maintained SDK includes Python workflow, activity, signal/update, testing, and observability surfaces. | Requires an additional server/service, deterministic workflow-code discipline, and careful payload retention. It is not the long-term audit ledger. | **Defer.** Add only after a simple scheduler has repeatedly lost/duplicated work or human review waits need durable state. |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Stateful agent graph, checkpointing, and human interruption could model analyst/critic flow. | MIT ([LICENSE](https://github.com/langchain-ai/langgraph/blob/main/LICENSE)); upstream presents durable execution, human-in-the-loop, memory, and agent-state features. | Overlaps with Pydantic AI/Temporal and can encourage agent-led control flow. Its ecosystem points to hosted LangSmith for much of debugging/evaluation. | **Do not adopt initially.** Re-evaluate only if Pydantic AI plus explicit Python orchestration becomes unmanageable. |
| [Microsoft Qlib](https://github.com/microsoft/qlib) | Research experiments, dataset handling, model evaluation, backtesting, and online workflow support. | MIT ([LICENSE](https://github.com/microsoft/qlib/blob/main/LICENSE)); upstream describes it as an AI-oriented quant-research platform with modeling, backtest, and workflow modules. | Large framework; data assumptions and US/options/intraday fidelity must be independently validated. A backtest result is not a trade approval. | **Optional, isolated lab** after a preregistered experiment plan and realistic costs/slippage data exist. |

## Why this is the smallest credible stack

PostgreSQL is the permanent memory; Pydantic AI produces *structured, bounded*
claims; OpenTelemetry makes a failure visible across the run.  That gives each
decision an inspectable chain without betting the system on multi-agent debate.
Temporal and LangGraph solve genuine workflow problems, but both add another
state machine.  Introducing either before the ledger and gate are proven would
make diagnosis harder, not easier.

## Required controls before expanding the stack

1. Define a versioned `EvidenceCard` and `DecisionEvent` contract.  Required
   fields include `as_of`, source IDs/hashes, invalidation condition, confidence
   basis, expected horizon, and an explicit `abstain` reason.
2. Run analyst cards independently: no card may read another card until its own
   hash is committed.  A critic can then challenge factual support and policy
   compliance, not create a hidden consensus.
3. Encode hard rejections outside the LLM: stale/missing data, prohibited
   session, missing liquidity/cost assumptions, contradictory side/risk,
   duplicate candidate, exposure cap, and insufficient forward evidence.
4. Treat every accepted shadow trade and every rejected near-miss as a resolved
   observation.  Score calibration, abstention quality, gate false positives,
   costs/slippage, and regime-specific performance; preserve losing outcomes.
5. Rule changes are proposals with a hypothesis, frozen comparison set,
   reviewer approval, versioned rollout, and rollback criterion.  They never
   rewrite historical events or auto-enable execution.

## Integration order and stop conditions

1. Migrate the current retained trade/history records into an append-only
   decision/outcome schema and prove reconciliation against the existing report.
2. Instrument the existing shadow pipeline and make one deterministic gate emit
   rejection reasons.
3. Add two bounded evidence producers plus one critic; compare their cards to
   the baseline gate on a forward sample.  Do not add more agents until they
   provide incremental, measured value.
4. Add Qlib only for a separately versioned research protocol.  Add Temporal
   only after recorded operational failures justify it.

The stop condition is important: a more elaborate stack is not progress unless
it improves forward calibration, execution-realism measurement, or auditability
without weakening the `execution_enabled: false` boundary.

## Source notes

All claims above are drawn from the owners' repository README, LICENSE, or
source materials, checked on 2026-09-02.  The evaluation intentionally excludes
broker APIs, broker MCPs, and execution repositories.

