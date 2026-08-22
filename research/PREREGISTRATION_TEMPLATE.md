# Trading Hypothesis Preregistration

Preregistration Schema: hypothesis-v1
Spec ID: replace-with-stable-candidate-id
Family ID: replace-with-experiment-family
Origin: research
Status: frozen
Spec Hash: sha256:<SPEC_HASH>

The hash is SHA-256 over this UTF-8 file with LF line endings and the `Spec
Hash` value replaced by `sha256:<SPEC_HASH>`. Run
`python scripts/preregistration_validator.py --write-hash <path>` once after
the rules are frozen, then do not edit the file after outcomes are inspected.

## Entry Rule

State the complete causal entry rule, including observation and action bars.

## Exit Rule

State stop, target, time exit, same-bar ordering, and invalidation behavior.

## Universe

State the fixed instruments and survivorship-safe membership policy.

## Timestamp Basis

State source timezone, session boundaries, and point-in-time availability.

## Execution Policy

execution_enabled=false
can_submit_orders=false

State ask-to-bid fills, order type, latency, and no-fill handling.

## Cost Stress

State commissions, fees, base slippage, and at least one doubled-cost stress.
