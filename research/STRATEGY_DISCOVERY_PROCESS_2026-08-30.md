# Strategy discovery process

This process prevents the scanner from treating its current strategy set as a
finished universe and prevents “implemented” from being mistaken for “tested.”

## Required lifecycle

1. **Intake:** Every materially different concept receives a stable taxonomy ID.
   A new timeframe, direction, or exit is a variant of the same economic family,
   not a new discovery.
2. **Evidence registration:** Every taxonomy ID must appear in
   `concept_evidence_registry_2026-08-30.json`. Missing rows make the audit exit
   nonzero. Evidence states are isolated-tested, partial-proxy, implementation-
   only, untested, or data-blocked.
3. **Gap ranking:** `strategy_concept_coverage_audit.py` ranks data-ready gaps.
   Social popularity and screenshots cannot mark a concept tested.
4. **Preregistration:** Definitions, matrix, costs, attempts, and gates freeze
   before results are read.
5. **Tournament:** Test the simplest causal standalone rule first. A negative
   standalone result may still justify later context-filter evaluation, but it
   cannot be an A+/B+ trigger.
6. **Forward shadow:** Historical survivors require a distinct forward ledger.
   Historical selection cannot approve live rank changes.
7. **Promotion:** Requires the existing completed-trade, trading-day, OOS,
   operational-health, liquidity, and manual-review gates.

## Current frontier after the first expansion

- Isolated evidence now exists for CBC strong flip, session sweep/reclaim, and
  context-gated engulfing; none survived as standalone triggers.
- FVG remains proxy-only because EMA direction is not true HTF direction.
- Highest-priority untouched families include isolated classical pattern tests,
  ICT CISD, STRAT 2-1-2 and 3-1-2, strict FTFC as a context challenger, confirmed
  equal-extreme pools, causal POC rejection, OTE, and Wyckoff phase logic.
- True delta and GEX remain blocked until the required provenance-grade data is
  available.

The dashboard must continue displaying both coverage percentage and the priority
queue. A failed tournament closes one definition; it does not close discovery.

