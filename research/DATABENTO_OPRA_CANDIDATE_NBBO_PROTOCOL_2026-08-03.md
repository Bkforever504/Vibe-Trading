# Databento OPRA Candidate NBBO Protocol

Date frozen: 2026-08-03

## Purpose

Acquire only the licensed consolidated quote history needed to replay option
structures that the bot actually formed. This is a data-coverage operation,
not a strategy search.

## Frozen Request

- Provider dataset: `OPRA.PILLAR`.
- Schema: `cbbo-1s`, Databento's one-second consolidated BBO.
- Symbology: exact OCC contracts already frozen in
  `data/options_shadow_twin_log.jsonl`, converted to OPRA's six-character
  padded root format.
- Start: five seconds before the earliest candidate timestamp.
- End: the earlier of the latest candidate evaluation end and 30 minutes
  before download time, unless an earlier explicit end is supplied.
- No parent-symbol or full-chain request is allowed.
- The command estimates cost by default. Download requires `--download` and
  aborts above `--max-cost`.
- Cost is computed from Databento's billable-byte endpoint and the frozen
  2026-08-03 official historical `cbbo-1s` rate of $2/GiB. Both values and the
  rate date are explicitly labeled in the manifest.
- Existing immutable DBN cache is reused and never overwritten.

## Normalization

- `ts_recv` is the observation and quote timestamp for the sampled CBBO.
- `bid_px_00` and `ask_px_00` are mapped to bid and ask.
- Raw padded OPRA symbols are converted back to compact OCC symbols.
- Invalid, crossed, zero, or unmapped records are retained only in audit
  counts and are not written as executable quotes.
- Every output row is labeled `databento_opra_cbbo_1s` with dataset, schema,
  source cache, and request fingerprint.

## Authority

The adapter cannot submit broker orders, alter candidates, generate new
contracts, or promote a strategy. The resulting quote file is consumed by the
preregistered options NBBO curriculum. A small or unresolved sample remains
insufficient evidence even when quote coverage is complete.

## Incremental Nightly Amendment

- The nightly lane selects only candidate IDs not already resolved by the
  licensed NBBO curriculum.
- Existing normalized coverage is indexed per OCC contract. The next request
  starts two seconds before the least-advanced relevant contract so boundary
  continuity can be audited without downloading the full lifecycle again.
- Existing and new rows merge by `(symbol, observed_at)` and remain sorted;
  overlap replaces the duplicate deterministically.
- If every candidate is resolved or provider availability has not advanced,
  the command exits successfully without a billable request.
- The registered weekday task has a hard $0.05 per-run request ceiling. It
  cannot place orders and cannot promote a strategy.
