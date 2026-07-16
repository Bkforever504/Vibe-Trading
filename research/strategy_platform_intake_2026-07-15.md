# Strategy Builder Platform Intake

Date: 2026-07-15

Purpose: identify reusable workflow and architecture patterns for the bot-first strategy pipeline. This is not a ranking of claimed trading performance.

## Evidence Quality

The exact `TRNDLINE` product shown in the supplied screenshots was not independently discoverable through public search. The screenshots demonstrate a natural-language strategy builder, chart insight card, historical measurement, and setup alerts, but they do not establish audited performance or implementation details.

A last30days run covered Reddit, Hacker News, and Polymarket from 2026-06-16 through 2026-07-15. It returned broad interest in English-to-backtest workflows but no independently verified evidence that an AI strategy builder produces profitable strategies. X returned HTTP 403 and YouTube transcript coverage was unavailable, so the social evidence is incomplete and receives low weight.

Primary product documentation and open-source repositories receive the highest weight below.

## Commercial Workflow References

| Platform | Verified public capability | Decision | Local use |
|---|---|---|---|
| [TrendSpider](https://trendspider.com/product/strategy-development-and-backtesting-tools/) | Natural-language/visual rule building, strategy testing, forward testing, and alerts | Adopt workflow | One continuous intake, validation, shadow-monitoring, and alert lifecycle |
| [Capitalise.ai](https://capitalise.ai/) | Everyday-English scenarios, backtesting, simulation, monitoring, and notifications | Adopt workflow | Explicit scenario state and understandable matched/not-matched explanations |
| [Composer](https://www.composer.trade/) | Natural-language strategy creation, editable structure, benchmarked backtests | Adopt workflow | Editable canonical packet and benchmark comparison |
| [QuantConnect](https://www.quantconnect.com/) | Point-in-time research, fee/slippage/spread modeling, parameter sensitivity, detailed backtest inspection | Adopt validation standard | Data provenance, cost model, parameter stability, and reproducible run artifacts |

No proprietary strategy, signal, training data, or platform code will be copied.

## Open-Source Candidates

### HKUDS/Vibe-Trading

Source: [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading), MIT license.

Decision: evaluate selected patterns.

Useful patterns:

- `run_card.json` and Markdown run artifacts for reproducibility.
- Persistent research memory with inspect/list/search/forget controls.
- Trace and artifact inspection instead of a single summary score.
- Shadow-account comparison and journal-derived rule extraction.
- Research and simulation authority separated from live trading.

Local status: the repository's `AI-Trader` companion is already present under `research/external_repos`, but HKUDS/Vibe-Trading itself is not imported. A source-level license and dependency audit is required before copying any implementation.

### VibeTradingLabs/vibetrading

Source: [VibeTradingLabs/vibetrading](https://github.com/VibeTradingLabs/vibetrading), MIT license.

Decision: evaluate selected patterns; reject deployment path.

Useful patterns:

- Narrow `describe -> generate -> validate -> backtest -> analyze` interface.
- Static validation result separate from model commentary.
- Explicit slippage input and structured metric output.
- Strategy templates that do not require a model call.

Rejected for this system:

- Generated code flowing directly toward crypto live deployment.
- LLM analysis serving as promotion evidence.
- Reusing one adapter unchanged in research and live execution without the local execution guard.

### QuantConnect LEAN

Source: [QuantConnect/Lean](https://github.com/QuantConnect/Lean), Apache 2.0 license.

Decision: future adapter evaluation.

Potential value:

- Brokerage, margin, fee, slippage, spread, and fill modeling.
- Point-in-time multi-asset event engine.
- Separation of algorithm logic from brokerage simulation.

Not phase one because adding LEAN would materially expand dependencies and operational complexity. The local pipeline contract must stabilize first.

### QSTrader

Source: [mhallsmoore/qstrader](https://github.com/mhallsmoore/qstrader), MIT license.

Decision: adopt architecture concept, no dependency.

Useful pattern: signal generation, portfolio construction, risk, execution simulation, and accounting are distinct modules. This supports the local rule that a research signal never receives order authority merely because it exists.

## Adopt Now

1. Canonical editable strategy packet instead of opaque generated code.
2. Deterministic validation after language interpretation.
3. Reproducible run cards with packet hash, dataset windows, costs, code version, and artifacts.
4. Validation and model commentary as separate authorities.
5. Scenario monitoring with precise match and rejection reasons.
6. Point-in-time data, spread/slippage, benchmark, OOS, walk-forward, and multiple-testing requirements.
7. Persistent failed trials so refinement cannot erase unsuccessful attempts.

## Evaluate Later

1. LEAN as a backtest adapter after the packet interface stabilizes.
2. A restricted subprocess for generated adapters with OS-level network and filesystem controls.
3. Trace visualization and run-card comparison in a later dashboard phase.
4. Research-memory search with explicit retention and deletion controls.
5. Import adapters for Pine, LEAN, and other engines behind the same packet contract.

## Reject

1. Proprietary signal or strategy copying.
2. Social-media screenshots, testimonials, or percentage returns as evidence.
3. Automatic live promotion or generated broker code.
4. LLM self-scoring as statistical validation.
5. Parameter optimization that does not count every attempted trial.
6. Historical option-return claims without point-in-time option quotes and executable fill assumptions.
7. Silent defaults for missing stops, exits, sizing, holdout windows, or costs.

## Implementation Consequence

No external runtime package is added in phase one. The local implementation uses the standard library plus the repository's existing research stack. External repositories remain references until a separate license, dependency, security, and overlap audit approves a specific module-level intake.
