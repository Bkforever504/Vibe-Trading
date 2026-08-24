# Trading Hypothesis Preregistration

Preregistration Schema: hypothesis-v2
Spec ID: replace-with-stable-candidate-id
Family ID: replace-with-experiment-family
Origin: research
Status: frozen
Spec Hash: sha256:<SPEC_HASH>
Universe ID: replace-with-stable-universe-id
Universe Version: replace-with-version
Universe Hash: sha256:0000000000000000000000000000000000000000000000000000000000000000
Membership As Of: YYYY-MM-DD

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

## Experiment Family & Multiple Testing

Freeze the experiment-family ID, enumerate every challenger in the family, and
use Benjamini-Hochberg adjusted q-values at alpha 0.05. Do not remove failed
challengers from the denominator.

## Regime Coverage

Require at least eight independent dates in each of trend, chop, high-vol, and
low-vol before promotion. State the point-in-time regime classifier.

## Latency Budget

Define the setup's expected move window and require p90 alert latency to remain
at or below 20% of that window, with at least 30 measured alerts.

## Blocker EV Review

If this changes a blocker, compare blocked winners and losses by net expected
value after costs and loss severity. Raw winner/loss counts are insufficient.

## Data Repair & Backfill

Any repaired producer must backfill the affected interval, re-grade every
affected observation, and leave zero known contaminated outcomes before use.

## Decay & Revalidation

Require at least three rolling validation windows, positive latest Brier skill,
and revalidation every 30 calendar days. Stale promotion returns to shadow
review; it never gains order authority.

## Universe Version

Freeze the universe version, SHA-256 membership hash, membership-as-of date,
and drift status. Any membership change creates a new comparable version.
