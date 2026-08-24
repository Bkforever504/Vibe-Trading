# Trading Hypothesis Preregistration — Equity ORB Scout v1

Preregistration Schema: hypothesis-v2
Spec ID: equity-orb-scout-v1
Family ID: equity-orb-scout
Origin: research
Status: frozen
Spec Hash: sha256:61d15241050297f84a3d1bcf0fdc2fa152885268d88cbed2891b61406c99fc27
Universe ID: equity-scout-hot20-plus-sp100-liquid
Universe Version: equity-scout-hot20-plus-sp100-liquid-v1
Universe Hash: sha256:e69d15099e63f70b4e41f4c8d9457074581063b556cb678671abf3102a8d46a0
Membership As Of: 2026-08-23

This scout candidate exists to catch the best intraday opening-range breakouts
across a broad, liquid US equity universe. Its purpose is dashboard visibility
and evidence discovery. It is not promotion-eligible on yfinance proxy quotes;
promotion requires Kenny sign-off and a swap to executable NBBO from Alpaca IEX
or equivalent.

## Entry Rule

Use RTH only. Freeze the 09:30:00–09:44:59 ET opening range per symbol as the
15-minute high/low. Enter only after the first completed 5-minute bar between
09:45 and 10:30 ET closes at least 0.10% beyond the range, with same-time RVOL
at least 1.5 vs the prior-five-session average, VWAP-aligned (close above VWAP
for long, below for short), and no listed 09:30–15:30 ET macro veto. Only the
first trigger of the day per symbol is eligible. If any input is missing at the
decision timestamp the setup is skipped.

## Exit Rule

Place the stop one cent beyond the opposite opening-range boundary. Exit 50% at
one opening-range width and the remainder at two widths. After T1 move the stop
to breakeven plus one cent. If at least 0.5R after 15 minutes without T1, move
to breakeven. Exit all remaining exposure by 15:55 ET. When stop and target are
both touched inside an unresolved bar, score the adverse event first.

## Universe

Frozen membership at `data/universes/equity_scout_v1_membership_2026-08-23.json`.
The universe is the union of a hot list (SPY, QQQ, IWM plus 20 highest-average-
dollar-volume names as of 2026-08-22) and the top 100 S&P 500 names by trailing
30-day dollar volume. Membership is immutable; a new universe version and spec
hash are required for any change.

## Timestamp Basis

Use America/New_York exchange timestamps and completed bars only. RVOL, VWAP,
and macro inputs must have been available at the decision timestamp. No later
revisions may enter historical decisions.

## Execution Policy

execution_enabled=false
can_submit_orders=false

Shadow-log the signal and show the entry, stop, targets, VWAP, RVOL, and grade
for manual review. This spec has no broker or order authority.

## Cost Stress

Use $0.005/share commission plus one cent slippage on entry and exit. Require
positive net expectancy lower 95% confidence bound at base costs and under
doubled commissions and slippage before any promotion review.

## Experiment Family & Multiple Testing

The frozen experiment family includes every candidate recorded in
`data/experiment_family.jsonl`. Promotion uses Benjamini-Hochberg at alpha 0.05
with the exact immutable ledger family size. Missing raw p-values produce HOLD.

## Regime Coverage

Require at least 100 resolved outcomes, 30 independent dates overall, and eight
independent dates in each of trend, chop, high-vol, and low-vol. Regimes use
point-in-time inputs; missing regimes cannot be inferred retrospectively.
Per-symbol outcomes pool across the universe.

## Latency Budget

Define the expected move window from the completed 5m trigger bar through the
frozen 15:55 ET flat time. At least 30 alerts are required and p90 alert
latency must be no more than 20% of that window.

## Blocker EV Review

This is a new detector, not a blocker-removal change. Any later blocker change
must show a positive net-after-cost expected-value lower 95% confidence bound
including the severity of blocked losses and winners; raw counts do not qualify.

## Data Repair & Backfill

Any repair to bars, RVOL, VWAP, or macro producers must identify the affected
interval, complete point-in-time backfill, re-grade every affected outcome, and
leave zero known contaminated outcomes before promotion.

## Decay & Revalidation

Require at least three rolling validation windows, positive latest Brier skill,
and revalidation within 30 calendar days. A stale or failing approved candidate
returns to paper review. A single miss cannot alter this frozen rule.

## Promotion Blockers

Evidence Tier: proxy_ohlcv_non_executable
Evidence Blockers: executable_quotes_required, kenny_signoff_required

Outcomes recorded under this candidate are surfaced on the dashboard as scout
signals only. They do not count toward the promotion gate until both blockers
are removed by an explicit approval commit.

## Universe Version

Universe ID, version, membership SHA-256, and membership-as-of date above are
immutable ledger identity. Roll-policy or membership changes require a new
candidate and cannot be merged into this candidate's historical measurements.
