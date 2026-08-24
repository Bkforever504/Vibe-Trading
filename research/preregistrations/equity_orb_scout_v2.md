# Trading Hypothesis Preregistration — Equity ORB Scout v2 (A+ Filters)

Preregistration Schema: hypothesis-v2
Spec ID: equity-orb-scout-v2
Family ID: equity-orb-scout
Origin: research
Status: frozen
Spec Hash: sha256:9fc403eecaa1b50b0f8742fa7fad5e90a40d50ffaee7bb7b2ea6d748d130a51e
Universe ID: equity-scout-hot20-plus-sp100-liquid
Universe Version: equity-scout-hot20-plus-sp100-liquid-v1
Universe Hash: sha256:e69d15099e63f70b4e41f4c8d9457074581063b556cb678671abf3102a8d46a0
Membership As Of: 2026-08-23

Scout v2 replaces scout v1 as the A+ discovery layer. It adds six selectivity
filters and a re-weighted grade formula on top of the same universe, opening
range, exit rule, cost stress, and promotion boundaries. Scout v1 continues
shadow-logging in parallel for A/B comparison.

## Entry Rule

Use RTH only. Freeze the 09:30:00–09:44:59 ET opening range per symbol as the
15-minute high/low. Enter only after the first completed 5-minute bar between
09:45 and 10:30 ET closes at least 0.10% beyond the range, with same-time RVOL
at least 1.5 vs the prior-five-session average, VWAP-aligned (close above VWAP
for long, below for short). Only the first trigger of the day per symbol is
eligible. If any required input is missing at the decision timestamp the setup
is skipped.

### A+ Filters (all must pass — otherwise setup is skipped)

1. Daily 20-EMA trend: long only when prior-day close is above the 20-day EMA
   on daily closes; short only when below. EMA computed on completed daily bars
   through the prior session close.
2. Relative strength vs SPY: five-session cumulative return of the symbol minus
   SPY. Long requires ≥ +0.5%; short requires ≤ -0.5%. Computed from completed
   daily closes through the prior session close.
3. Earnings blackout: skip if the symbol has a scheduled earnings release today
   or tomorrow per the earnings-calendar feed. Missing calendar coverage counts
   as blocked.
4. Macro veto: skip if the macro-catalyst calendar reports any high-impact event
   in the 09:30–15:30 ET window today (unchanged from v1).
5. Sector rotation confirmation: skip when the symbol's GICS sector is ranked in
   the bottom two of the sector-rotation ranker for long trades, or top two for
   short trades. Sector rank from prior-day close.
6. Time-of-day EV weight: assign 1.00 for a 09:45–10:15 ET trigger, 0.85 for
   10:15–10:30 ET. Later triggers already excluded by the 10:30 ET window.

### Alternate Setup: Gap-and-Go (parallel path)

If the symbol gaps open ≥ 2.0% versus the prior daily close AND opening 5m bar
(09:30–09:35 ET) closes in the direction of the gap AND opening bar volume ≥
2× prior 20-day 5m first-bar average, then generate an alternate entry at that
close, stop = 09:30 low (for gap-up long) or 09:30 high (for gap-down short),
T1 = 1× (entry − stop), T2 = 2× (entry − stop). Gap-and-go must still pass
filters 1, 2, 3, 4, 5 above and time-weight = 1.10 (bonus). Time exit and BE
rules match the primary path.

## Exit Rule

Place the stop one cent beyond the opposite opening-range boundary (or the
09:30 bar boundary for the gap-and-go path). Exit 50% at one opening-range
width and the remainder at two widths. After T1 move the stop to breakeven
plus one cent. If at least 0.5R after 15 minutes without T1, move to breakeven.
Exit all remaining exposure by 15:55 ET. When stop and target are both touched
inside an unresolved bar, score the adverse event first.

## Grade v2 Formula

Composite score in [0.0, 1.0] blended from six normalized components:

- 0.25 × min(RVOL, 5.0) / 5.0
- 0.20 × min(displacement_pct × 200, 1.0)
- 0.15 × vwap_pass (0 or 1)
- 0.15 × rel_strength_component (clamped, 0.0-1.0)
- 0.10 × ema_trend_component (0 or 1, gated by filter 1)
- 0.10 × sector_rank_component (top-2 sector = 1.0, mid = 0.5, bottom = 0.0)
- 0.05 × time_of_day_weight

Setups with grade < 0.55 are demoted from the dashboard top-N but still logged.
Top-20 by grade are Discord-alerted; the rest are shadow-only.

## Universe

Same frozen membership file as scout v1:
`data/universes/equity_scout_v1_membership_2026-08-23.json`. Membership is
immutable; a new universe version requires a new candidate and spec hash.

## Timestamp Basis

Use America/New_York exchange timestamps and completed bars only. RVOL, VWAP,
EMA, RS, earnings, sector-rotation, and macro inputs must have been available
at the decision timestamp. No later revisions may enter historical decisions.

## Execution Policy

execution_enabled=false
can_submit_orders=false

Shadow-log the signal, entry, stop, targets, VWAP, RVOL, RS, sector rank, and
grade for manual review. This spec has no broker or order authority.

## Cost Stress

Use $0.005/share commission plus one cent slippage on entry and exit. Require
positive net expectancy lower 95% confidence bound at base costs and under
doubled commissions and slippage before any promotion review.

## Experiment Family & Multiple Testing

Frozen experiment family. Promotion uses Benjamini-Hochberg at alpha 0.05 with
the exact immutable ledger family size. Missing raw p-values produce HOLD.

## Regime Coverage

Require at least 100 resolved outcomes, 30 independent dates overall, and eight
independent dates in each of trend, chop, high-vol, and low-vol.

## Latency Budget

Expected move window from the completed 5m trigger bar through 15:55 ET flat
time. At least 30 alerts required; p90 alert latency no more than 20% of that
window.

## Blocker EV Review

Any later blocker change must show a positive net-after-cost EV lower 95% CI
including severity of blocked losses and winners; raw counts do not qualify.

## Data Repair & Backfill

Any repair to bars, RVOL, VWAP, EMA, RS, earnings, sector, or macro producers
must identify the affected interval, complete point-in-time backfill, re-grade
every affected outcome, and leave zero contaminated outcomes before promotion.

## Decay & Revalidation

Three rolling validation windows, positive latest Brier skill, revalidation
within 30 calendar days. A stale or failing approved candidate returns to paper
review.

## Promotion Blockers

Evidence Tier: proxy_ohlcv_non_executable
Evidence Blockers: executable_nbbo_quotes_required, kenny_signoff_required

Outcomes surface on the dashboard as scout signals only. They do not count
toward the promotion gate until both blockers are removed by an explicit
approval commit.

## Universe Version

Universe ID, version, membership SHA-256, and membership-as-of date above are
immutable ledger identity. Roll-policy or membership changes require a new
candidate.
