# Bot-First Strategy Pipeline Design

Date: 2026-07-15

## Objective

Build one research-only entry point that converts a plain-English trading thesis into a deterministic, versioned strategy packet, validates it, routes it through the repository's existing backtest and evidence systems, and prepares qualified strategies for shadow monitoring and alerts.

The pipeline accelerates idea testing. It does not let generated code place orders, change live gates, promote itself, or claim profitability from historical results.

## Existing Foundation

The repository already contains most required authorities:

- `research/strategy_intake.py` scores rule completeness and ambiguity.
- `research/pine_strategy_lab.py` detects repainting and unrealistic Pine assumptions.
- `research/pine_strategy_lab_backtest.py` supports in-sample, out-of-sample, and walk-forward evaluation.
- `scripts/strategy_leak_audit.py` checks common data leakage patterns.
- `scripts/edge_trial_ledger.py` records immutable trials and controls multiple-testing promotion review.
- Scheduled shadow scanners, health reports, and Discord-capable alert paths provide forward monitoring.
- `strategies/strat_30m_continuation.py` and `scripts/strat_30m_continuation_shadow.py` provide the first linked end-to-end example.

The missing capability is orchestration and a canonical strategy contract.

## Research Findings

Comparable platforms confirm the product workflow but do not prove trading edge:

- [TrendSpider Strategy Development](https://trendspider.com/product/strategy-development-and-backtesting-tools/) combines natural-language or visual rules, backtesting, forward testing, and alerts. We should adopt the unified workflow, not its proprietary signals.
- [Capitalise.ai](https://capitalise.ai/) turns everyday English into backtests, simulations, monitoring, notifications, and automation. We should adopt explicit scenario monitoring and understandable rule feedback.
- [Composer](https://www.composer.trade/) turns natural-language goals into editable strategy structures and comparative backtests. We should adopt the editable structured representation and benchmark comparison.
- [QuantConnect](https://www.quantconnect.com/) emphasizes point-in-time data, fee/slippage/spread-adjusted backtests, parameter sensitivity, and detailed result inspection. These are validation requirements, not optional polish.

Open-source candidates for selective architecture intake:

- [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) is an MIT-licensed research workspace with natural-language backtests, reproducible run cards, persistent research memory, trace inspection, and shadow-account analysis. Highest-value patterns: run cards, artifact manifests, traceability, and memory controls.
- [VibeTradingLabs/vibetrading](https://github.com/VibeTradingLabs/vibetrading) is an MIT-licensed describe/generate/validate/backtest framework. Highest-value patterns: a narrow strategy interface, static validation result, cost-aware backtest call, and structured analysis output. Its crypto live-deployment path is out of scope.
- [QuantConnect LEAN](https://github.com/QuantConnect/Lean) is an open-source engine with realistic brokerage and data modeling. It is a future adapter candidate, not a dependency for phase one.
- [QSTrader](https://github.com/mhallsmoore/qstrader) cleanly separates signals, portfolio construction, risk, execution simulation, and accounting. Its authority separation is a useful reference.

Recent social research was thin and noisy. It produced one directly relevant current discussion and broad interest in English-to-backtest tools, but no independently verified evidence that any AI strategy builder creates profitable strategies. X and YouTube coverage failed in the research run, so product documentation and source code carry more weight than social claims.

## Architecture

### 1. Canonical Strategy Packet

Create a versioned schema with:

- Identity: strategy name, thesis, source, author, creation time, schema version, and content hash.
- Market scope: asset class, symbols or universe, timezone, session, timeframe, and option-specific contract rules when applicable.
- Rules: setup context, entry trigger, invalidation, stop, targets, trailing/partial exits, sizing, maximum concurrent positions, and cooldowns.
- Data contract: required bars, quotes, options fields, indicators, corporate-action handling, and point-in-time requirements.
- Research contract: dataset windows, benchmark, cost model, parameter ranges, fixed holdout, and forward-test requirements.
- Provenance: original prompt, normalized interpretation, assumptions, unresolved ambiguities, generated artifacts, and code version.
- Authority: `research_only`, `execution_enabled: false`, `can_submit_orders: false`, and `promotion_requires_human_approval: true`.

The packet is immutable after preregistration. A changed rule or parameter creates a new version and a new trial identity.

### 2. Plain-English Intake

The CLI accepts a prompt or a packet file. The language model may propose a structured packet, but deterministic validators decide whether it is usable.

The intake must stop at `needs_rules` when any material element is ambiguous, including entry timing, bar-close confirmation, stop behavior, exit priority, sizing, or data availability. It must never guess missing risk rules.

### 3. Validation Pipeline

Validation runs in this order:

1. Schema and rule completeness.
2. Supported indicator and operator validation.
3. Point-in-time data availability.
4. Lookahead, repaint, and leakage checks.
5. Cost, spread, slippage, and fill-model completeness.
6. Dataset and holdout immutability.
7. Static code safety and allowed-import checks.
8. In-sample backtest.
9. Out-of-sample and walk-forward evaluation.
10. Multiple-testing and overfitting governance.

Failure at any stage records a durable rejection with reasons. Failed attempts remain counted.

### 4. Adapter Boundary

Phase one supports deterministic local Python adapters only. Generated source runs in a restricted research subprocess with:

- No broker clients or order submission imports.
- No network access during evaluation.
- Read-only access to declared datasets.
- Runtime and memory limits.
- A narrow signal interface that returns desired research signals, not orders.

The orchestrator may generate an adapter draft, but a draft is not eligible for backtesting until static validation passes.

### 5. Trial and Artifact Lifecycle

Every run writes a reproducible run card containing:

- Strategy packet hash and trial ID.
- Dataset provenance and exact windows.
- Code version and dependency versions.
- Cost and fill assumptions.
- Metrics, benchmark comparison, equity curve path, trade list path, and diagnostics.
- Validation stages, warnings, blockers, and final decision.

Completed trials are appended to `scripts/edge_trial_ledger.py`. No result is overwritten. Refinements create child trials linked to their parent.

### 6. Shadow Monitoring and Alerts

Only candidates that pass the existing research gates can receive a shadow adapter. Shadow monitoring records every setup appearance, rejection, hypothetical entry, path, exit, and outcome.

Alerts describe a matched paper setup and its packet version. They do not recommend a live trade and cannot submit an order. Discord delivery reuses the repository's existing notification helper and remains optional when credentials are unavailable.

### 7. First Linked Strategy

The existing 30-minute Strat continuation strategy becomes the first canonical packet. The pipeline links to its current implementation and shadow scanner rather than duplicating logic. This proves that an existing researched strategy can be represented, validated, monitored, and traced end to end.

## CLI Surface

Primary commands:

```text
python scripts/strategy_pipeline.py intake --describe "..." --name "..."
python scripts/strategy_pipeline.py validate --packet <path>
python scripts/strategy_pipeline.py run --packet <path>
python scripts/strategy_pipeline.py show --run-id <id>
python scripts/strategy_pipeline.py list --status needs_rules|rejected|shadow_candidate
```

`intake` and `validate` are always safe. `run` means research execution only. There is no live command.

## Error Handling

- Invalid or incomplete prompts produce `needs_rules` with precise questions.
- Unsupported data or indicators produce `unsupported` without generating substitute logic.
- Dataset fetch failure leaves the trial unstarted; it does not reuse stale data silently.
- Adapter timeout or sandbox violation rejects the run and records the event.
- Artifact writes are atomic. Partial runs are labeled incomplete and never enter promotion review.
- Alert delivery failure is logged separately from strategy evaluation.

## Testing

Tests must prove:

- Identical packets produce identical hashes.
- Rule changes produce new identities.
- Ambiguous risk or exit rules fail closed.
- Generated adapters cannot import broker or network modules.
- Lookahead and unavailable point-in-time fields are rejected.
- Costs and holdout windows are required.
- Failed trials remain in the ledger and affect multiple-testing counts.
- The Strat example links to existing logic without duplication.
- All reports preserve `execution_enabled: false` and `can_submit_orders: false`.
- No command can place an order or change a live gate.

## Delivery Scope

Phase one delivers the schema, intake/validation CLI, adapter contract and sandbox, run cards, immutable trial integration, Strat example, tests, and a research report evaluating external candidates.

Phase one does not deliver a visual dashboard, automated live promotion, broker execution, free-form self-modifying strategies, paid data integration, or copied proprietary platform logic.

## Success Criteria

The implementation is complete when one command can turn a sufficiently precise thesis into a validated packet, produce reproducible research artifacts, register the result immutably, and identify the exact next stage. The existing Strat continuation strategy must complete the linked workflow while every generated artifact remains incapable of live execution.
