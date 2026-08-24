# Trading Hypothesis Preregistration — MES ORB 09:32 ET

Preregistration Schema: hypothesis-v2
Spec ID: mes-orb-0932-vix-v2
Family ID: mes-opening-breakout
Origin: research
Status: frozen
Spec Hash: sha256:1b5b00351729d29d41f9b58cf3bbe7ad66d5edda594d29d405af72279dd4fd5b
Universe ID: cme-mes-continuous
Universe Version: cme-mes-front-month-roll8-v1
Universe Hash: sha256:aabaf0268d8e08c686b4ea20d251550f6de0663d59ce363543e76e35595eb567
Membership As Of: 2026-08-22

This v2 wrapper preserves the Kenny-approved rules in
`research/FROZEN_STRATEGY_1_2026-08-22.md`. It adds governance controls only;
it does not expand entry, exit, sizing, or execution authority.

## Entry Rule

Use MES RTH. Freeze the 09:30:00–09:31:59 ET opening range. Enter only after
the first completed 5-minute bar through 09:45 ET closes at least 0.10% beyond
the range, with same-time RVOL at least 1.5, prior-close VIX in [15,25], HMM
state `trend`, no listed 09:30–15:30 ET macro event, and Monday/Wednesday/Friday.
Only the first trigger is eligible and the action timestamp is after that bar.

## Exit Rule

Place the stop one tick beyond the opposite opening-range boundary. Exit 50%
at one opening-range width and the remainder at two widths. After T1 move the
stop to breakeven plus one tick. If at least 0.5R after 15 minutes without T1,
move to breakeven. Exit all remaining exposure by 12:00 ET. When stop and target
are both touched inside an unresolved bar, score the adverse event first.

## Universe

MES front-month continuous contract only, rolled eight calendar days before
expiry. Membership policy canonical text: `CME MES front-month continuous
contract; roll eight calendar days before expiry; no retroactive membership
changes`. Changes require a new universe version and spec hash.

## Timestamp Basis

Use America/New_York exchange timestamps and completed bars only. VIX is the
prior available close; HMM, catalyst, and RVOL inputs must have been available
at the decision timestamp. No later revisions may enter historical decisions.

## Execution Policy

execution_enabled=false
can_submit_orders=false

Shadow-log the signal and show the entry, stop, targets, and blockers for manual
review. Model executable next-bar/tick fills and no-fill behavior. This spec has
no broker or order authority.

## Cost Stress

Use $0.35 commission per side per MES contract plus one tick of slippage on
entry and exit. Require positive net expectancy lower 95% confidence bound at
base costs and under doubled commissions and slippage.

## Experiment Family & Multiple Testing

The frozen experiment family includes every candidate recorded in
`data/experiment_family.jsonl`. Promotion uses Benjamini-Hochberg at alpha 0.05
with the exact immutable ledger family size. Missing raw p-values produce HOLD.

## Regime Coverage

Require at least 100 resolved outcomes, 30 independent dates overall, and eight
independent dates in each of trend, chop, high-vol, and low-vol. Regimes use
point-in-time inputs; missing regimes cannot be inferred retrospectively.

## Latency Budget

Define the expected move window from completed trigger bar through the frozen
12:00 ET time exit. At least 30 alerts are required and p90 alert latency must
be no more than 20% of that window.

## Blocker EV Review

This is a new detector, not a blocker-removal change. Any later blocker change
must show a positive net-after-cost expected-value lower 95% confidence bound
including the severity of blocked losses and winners; raw counts do not qualify.

## Data Repair & Backfill

Any repair to bars, VIX, HMM, catalyst, or RVOL producers must identify the
affected interval, complete point-in-time backfill, re-grade every affected
outcome, and leave zero known contaminated outcomes before promotion.

## Decay & Revalidation

Require at least three rolling validation windows, positive latest Brier skill,
and revalidation within 30 calendar days. A stale or failing approved candidate
returns to paper review. A single miss cannot alter this frozen rule.

## Universe Version

Universe ID, version, membership SHA-256, and membership-as-of date above are
immutable ledger identity. Roll-policy or membership changes require a new
candidate and cannot be merged into this candidate's historical measurements.
