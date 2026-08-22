# Verified Trader Evidence Pipeline Preregistration

Date frozen: 2026-07-25
Scope: external trader observations for research and shadow replay only

## Objective

Determine whether complete, timestamped external trader records contain
repeatable net expectancy after realistic observation delay and costs. Public
claims may nominate hypotheses, but they are not trading evidence.

## Fixed Source Tiers

| Source type | Base evidence score | Consent required | Intended use |
|---|---:|---:|---|
| `broker_csv` | 9 | yes | Historical fill and outcome replay |
| `snaptrade_activity` | 9 | yes | Historical fill and outcome replay |
| `collective2_signal` | 4 | no | Hypothesis only; published results are hypothetical |
| `robinhood_social_signal` | 8 | no | Verified, timestamped shadow signal replay |
| `kinfo_public_profile` | 7 | no | Broker-imported performance verification context only |
| `tradingview_webhook` | 6 | yes | Forward shadow signal replay |
| `manual_export` | 4 | yes | Quarantined unless complete |
| `x_api` | 2 | no | Candidate discovery and hypotheses only |
| `sec_form4` | 8 | no | Delayed swing context only |
| `cftc_cot` | 8 | no | Aggregate regime context only |

The base score cannot be increased from observed profitability. Outcomes must
not change provenance quality.

## Canonical Requirements

Every normalized record requires:

- source type and source identifier
- stable external identifier or deterministic fingerprint
- trader identifier
- event type
- source timestamp
- instrument symbol for trade-related events
- explicit side for signal, fill, and outcome events

Private or cooperating-trader sources require a non-empty consent reference.
Missing required fields fail closed into quarantine.

## Eligibility

- `execution_eligible` is always `false`.
- `promotion_eligible` is always `false`.
- X, SEC, and CFTC records are context-only.
- A live shadow signal requires evidence score at least 5, completeness at
  least 0.70, a source price, a point-in-time market price captured when the
  alert was observed, and observation latency no greater than 15 minutes.
- A timely signal without a point-in-time market price is replay-candidate
  evidence only. It cannot be labeled live-shadow eligible.
- Historical broker fills may be replay eligible without low observation
  latency, but they still require consent and fill fields.
- Quarantined records cannot enter performance statistics.
- Kinfo public profiles verify imported performance, not full-account coverage
  or copyable contract visibility. They remain context-only unless a separate
  immutable coverage manifest and exact trade export are obtained.
- Collective2 performance is explicitly hypothetical and cannot qualify a
  trader or signal for shadow replay by itself.

## Timeliness Score

| Observation latency | Score |
|---|---:|
| 0-5 seconds | 10 |
| 6-60 seconds | 9 |
| 61-300 seconds | 7 |
| 301-900 seconds | 5 |
| 901-3600 seconds | 3 |
| Over 3600 seconds | 1 |
| Unknown or negative | 0 |

Negative latency is a timestamp paradox and is quarantined.

## Deduplication

Prefer `(source_type, source_id, external_id)`. When no external identifier
exists, fingerprint canonical trader, instrument, event type, source timestamp,
side, price, and quantity. Duplicate fingerprints are skipped, never rewritten.

## Performance Gates

No source or trader can affect production rules automatically. A human-reviewed
future promotion proposal requires:

- at least 30 independently resolved forward observations, 100 preferred
- positive expectancy after measured fees, spreads, slippage, and source delay
- positive expectancy under doubled costs
- profit factor at least 1.20
- controlled maximum drawdown
- no dependence on the best 1% of outcomes
- acceptable performance across at least two market regimes
- an adversarial review by an agent that did not author the candidate

These are proposal gates, not automatic promotion rules.

Broker-linked evidence, sufficient broker outcomes, and verified source
coverage are separate labels. Thirty clean fill-derived outcomes only set
`broker_outcome_count_sufficient`. `coverage_verified` remains false until an
immutable completeness manifest proves the requested account history was not
selectively exported. Both are required before a legacy profile can be marked
verified.

Non-broker sources may not self-report outcome events. TradingView,
Collective2, manual, social, and regulatory outcome claims are quarantined and
excluded from all resolved-outcome statistics.

## Privacy And Security

The journal stores no brokerage credentials, OAuth tokens, webhook secrets, or
authorization headers. Raw payloads are recursively sanitized. Private records
must be collected with explicit permission and used only for the stated
research purpose.

## Stopping Rule

This initial implementation validates data integrity and shadow readiness. It
does not claim a profitable edge, place orders, subscribe to a paid service, or
retune existing strategies.
