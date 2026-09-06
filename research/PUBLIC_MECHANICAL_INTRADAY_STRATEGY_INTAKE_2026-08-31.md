# Public mechanical intraday strategy intake — 2026-08-31

Status: source intake only. No code, scanner, dashboard, ranking, alert, sizing, or execution behavior was changed. Every reported performance number below is an **unverified author claim**, not system evidence.

## Acceptance standard

An intake qualifies only when the public author source specifies: instrument/session, exact context/level, completed-bar trigger, invalidation/stop, exit or time-stop, and trading constraints. A complete description makes a candidate reproducible; it does **not** make it validated or promotable.

## Candidate A — NQ 5-minute BOS / order-block retest

**Source:** [Gtrades69/bos-ob-strategy README and public source code](https://github.com/Gtrades69/bos-ob-strategy)

**Status:** complete enough to preregister as a separate shadow-only candidate. It is not in the existing research intake under this source or exact formulation (repository search found no existing BOS/order-block candidate).

### Frozen source-matched rule chain

- **Instrument and session:** NQ futures; 07:30–13:00 CT. Use 5-minute bars for structure and 1-minute bars for entry. No more than eight trades/day, one position at a time, and a two-minute cooldown.
- **Level/context:** identify 5-minute swing highs/lows with a minimum 5-point depth. A bullish break of structure (BOS) requires a completed 5-minute candle body close above the last swing high plus a higher-high/higher-low trend; bearish is the symmetric lower-low/lower-high case.
- **Entry-zone construction:** after the BOS bar has completed, form eligible zones from (1) the last opposing 5-minute candle body before BOS, (2) the BOS candle body, and (3) the last opposing 1-minute candle body within the BOS five-minute interval.
- **Completed-bar trigger / entry:** wait for a later 1-minute bar to touch an active zone and close within five NQ points of its edge. Enter at that 1-minute close, modeled with 0.50 points adverse slippage. No wick-only BOS signal and no zone exists before the completed BOS bar.
- **Invalidation / stop:** long stop is the source order-block low minus one point; short stop is its high plus one point. Reject entries requiring more than 30 points of risk.
- **Exit:** target is 1.1R. The source specifies bracket-style stop/target handling but does not state an independent time-stop; the parent research implementation must add a preregistered end-of-session flatten rule for a fair test.

### Source-quality and bias treatment

The repository includes public backtest/audit files and explicitly documents completed-bar sequencing. That is stronger than a social post, but its claimed 61% win rate, 1.70 profit factor, and dollar P&L have not been independently reproduced. The repository has no external validation, no observable live fills, and an author-selected one-year sample. Treat it as a hypothesis only; do not copy its claimed performance.

### Required research implementation constraints

1. Keep this distinct from the existing level-sweep, FVG, or generic opening-range families; it is a 5m-BOS-to-1m-retest family.
2. Use NQ/MNQ-compatible continuous-futures data with a documented roll method and 1-minute data. Do not proxy the 1-minute entry mechanics from 5-minute data.
3. Define a conservative time stop and same-bar stop/target ordering before running. Use next-eligible-bar execution where bar-close timing makes the claimed fill impossible.
4. Test costs and slippage independently, then use date-blocked out-of-sample and forward shadow evidence. No promotion to live execution.

## Rejected source B — simple NQ 30-minute ORB

**Source:** [asdtroll3/ORB-Backtester](https://github.com/asdtroll3/ORB-Backtester)

This source is mechanically complete: NQ 5-minute bars, 09:30–10:00 ET range, first 5-minute close above range high, opposite-range stop, 1R target, first-breakout-only, and 14:00 ET time exit. It is rejected as a **new** candidate because it is a straightforward opening-range-breakout variant already represented by the existing opening-range research families. It may be used later as an independently specified benchmark configuration, not a new edge claim.

## Rejected source C — Flat Moon Society MNQ ORB code

**Source:** [FTM_OPENING_RANGE_BREAKOUT_MNQ_v1_8_0_RC3](https://gist.github.com/flatmoonsociety/15652fdecda9de12ac833e6b8c26d1b3)

The source contains detailed MNQ timing and completed-bar language, but labels itself `UNCOMPILED_UNRECONCILED_DRAFT` and includes a large adaptive/model-driven decision stack. It is rejected until the author provides a compiled, reconciled release and an independently reproducible rule specification. A large code file is not validation.

## Rejected source D — NQ ORB volume-profile retracement

**Source:** [dws-data/nas-orb-backtester](https://github.com/dws-data/nas-orb-backtester)

The source defines a 09:30–09:45 ET range, 1-minute close confirmation, and retracement to an opening-range volume-profile level. It does **not** publish the exact breakout threshold, target construction, entry cutoff, or force-close time in the reviewed documentation, so it fails the mechanical completeness gate.

## Decision

Only Candidate A is eligible for a separately preregistered shadow tournament. All sources remain outside operational logic until independently tested on source-compatible data with costs, temporal validation, and forward outcomes.
