# Trading Hypothesis Preregistration — MES Reopen Drift

Preregistration Schema: hypothesis-v2
Spec ID: mes-reopen-drift-v2
Family ID: mes-overnight-drift
Origin: research
Status: frozen
Spec Hash: sha256:3a345679af8d94402cd8a0d06406635f093aa843fa24dd1324d66429144f42ad
Universe ID: cme-mes-continuous
Universe Version: cme-mes-front-month-roll8-v1
Universe Hash: sha256:aabaf0268d8e08c686b4ea20d251550f6de0663d59ce363543e76e35595eb567
Membership As Of: 2026-08-22

This v2 wrapper preserves the Kenny-approved rules in
`research/FROZEN_STRATEGY_3_2026-08-22.md`. It adds governance controls only;
it does not expand entry, exit, sizing, or execution authority.

## Entry Rule

After the CME reopen, use the completed 17:00–17:30 CT MES bar. Long requires
the prior RTH close in the top 40% of its range and above RTH VWAP; short uses
the bottom 40% and below VWAP. Require same-time ETH volume at least 0.6 times
the prior-five-session average, prior-close VIX in [12,28], 100-bar 1-hour ETH
Hurst at least 0.52, and no next-day FOMC, CPI, NFP, ECB, or BOJ event. Mixed
bias is a skip and only the first trigger is eligible.

## Exit Rule

Stop at 1.5 ATR(14) measured on completed 30-minute ETH bars. Exit 50% at 1R
and the remainder at 2.5R or 08:30 ET, whichever occurs first. After T1 trail
to entry plus 0.25 ATR. Exit early after four hours at -0.5R without T1; after
two hours at +1R without T1 move the stop to entry. Score adverse-first when
intrabar order is unresolved and force all exposure flat by 08:30 ET.

## Universe

MES front-month continuous contract only, rolled eight calendar days before
expiry. Membership policy canonical text: `CME MES front-month continuous
contract; roll eight calendar days before expiry; no retroactive membership
changes`. Changes require a new universe version and spec hash.

## Timestamp Basis

Use America/Chicago for the reopen and America/New_York for the 08:30 exit and
macro calendar, with explicit timezone conversion. Use completed bars and only
VIX, VWAP, Hurst, volume, and catalyst values available at decision time.

## Execution Policy

execution_enabled=false
can_submit_orders=false

Shadow-log the candidate for manual review. Model next-actionable-price fills,
liquidity rejection, and no-fill behavior. Overnight approval and any future
Kenny sign-off remain separate; this spec has no broker or order authority.

## Cost Stress

Use $0.35 commission per side per MES contract plus two ticks of slippage on
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

Define the expected move window from the completed 17:30 CT trigger bar through
the frozen 08:30 ET exit. At least 30 alerts are required and p90 alert latency
must be no more than 20% of that window.

## Blocker EV Review

This is a new detector, not a blocker-removal change. Any later blocker change
must show a positive net-after-cost expected-value lower 95% confidence bound
including the severity of blocked losses and winners; raw counts do not qualify.

## Data Repair & Backfill

Any repair to ETH bars, RTH VWAP, VIX, Hurst, catalyst, or volume producers must
identify the affected interval, complete point-in-time backfill, re-grade every
affected outcome, and leave zero known contaminated outcomes before promotion.

## Decay & Revalidation

Require at least three rolling validation windows, positive latest Brier skill,
and revalidation within 30 calendar days. A stale or failing approved candidate
returns to paper review. A single miss cannot alter this frozen rule.

## Universe Version

Universe ID, version, membership SHA-256, and membership-as-of date above are
immutable ledger identity. Roll-policy or membership changes require a new
candidate and cannot be merged into this candidate's historical measurements.
