# Trading Hypothesis Preregistration — Equity Ignition–Contraction–Continuation v1

Preregistration Schema: hypothesis-v2
Spec ID: equity-ignition-contraction-continuation-v1
Family ID: equity-swing-continuation
Origin: research
Status: frozen
Spec Hash: sha256:c3ba4bac6145e2c4a05935e17aa92673acf5f827ca36b3a2ffb5453e8a65a5fd
Universe ID: equity-scout-hot20-plus-sp100-liquid
Universe Version: equity-scout-hot20-plus-sp100-liquid-v1
Universe Hash: sha256:e69d15099e63f70b4e41f4c8d9457074581063b556cb678671abf3102a8d46a0
Membership As Of: 2026-08-23

## Entry Rule

Use completed adjusted daily bars only. A qualifying ignition session closes
at least 2% above its prior close with volume at least 1.8 times the preceding
20-session average. It must be followed by a two-to-ten-session base no wider
than 8% of the ignition close whose average volume is no more than 75% of the
ignition volume. The latest completed session must close above the prior base
high on at least 1.3 times its preceding 20-session average volume, with
EMA(8) above EMA(21) above EMA(50), 20-session relative return versus SPY of
at least 3%, and its mapped sector ETF outperforming SPY over 20 sessions.

The setup becomes `SHADOW_READY` only after the daily breakout bar completes.
The next-session manual-review trigger is breakout high plus 0.05 ATR(14).
Missing benchmark, sector, volume, or completed-bar evidence fails closed.

## Exit Rule

The research invalidation is below the lower of the completed base low and
EMA(21), less 0.10 ATR(14). The frozen target is 2R. Cancel the next-session
review if the opening gap consumes the target, price opens below invalidation,
or required evidence becomes stale. Unresolved same-bar stop/target touches
are scored adverse-first. Any unresolved position is marked to the final
completed regular-session bar; this scanner never submits an exit.

## Universe

Use only the 121 immutable members in
`data/universes/equity_scout_v1_membership_2026-08-23.json`. The scanner may
not add a current winner after observing its move. Delistings and missing bars
remain in the denominator and are labeled unavailable rather than removed.

## Timestamp Basis

Daily bars use their exchange-session close and are not actionable until the
session is complete. EMA, ATR, relative strength, sector rank, and volume
comparisons use only information available at that close. The scheduled scan
runs at 15:20 America/Chicago after the regular US equity close.

## Execution Policy

execution_enabled=false
can_submit_orders=false

This is a read-only shadow challenger. Entry, stop, and target are manual-review
levels, not orders. Before any promotion review, executable NBBO quotes must
replace proxy fills. Base research fills are next-session ask for longs and
exit bid, with no fill if the trigger is skipped by more than 0.25 ATR.

## Cost Stress

Score $0.005 per share per side plus one cent per share slippage on entry and
exit, and a doubled-cost stress of $0.01 per share per side plus two cents
slippage. Promotion requires a positive net-expectancy lower 95% confidence
bound under both assumptions.

## Experiment Family & Multiple Testing

Family `equity-swing-continuation` initially contains this single frozen
candidate. Every later threshold or exit variant increments the immutable
family size. Promotion uses Benjamini–Hochberg adjusted q-values at alpha 0.05;
failed variants remain in the denominator.

## Regime Coverage

Require at least 100 resolved outcomes, 30 independent entry dates, and at
least eight independent dates in each of trend, chop, high-volatility, and
low-volatility regimes. Regimes must be assigned point-in-time by the frozen
HMM/RV-IV producers, never retrospectively.

## Latency Budget

The expected decision window starts at the completed daily breakout and ends
30 minutes after the next regular-session open. At least 30 measured alerts
are required and p90 alert latency must not exceed 20% of that window. A late
alert becomes no-chase evidence, not a simulated fill.

## Blocker EV Review

Any proposed change to the sector, volume, EMA, gap, or staleness blockers
must compare blocked winners and losses using net-after-cost expected value and
loss severity. Raw win/loss counts cannot justify loosening a blocker.

## Data Repair & Backfill

A repaired daily-bar, universe, benchmark, sector, or corporate-action source
must identify the contaminated interval, point-in-time backfill it, re-grade
every affected observation, and leave zero known contaminated outcomes before
those outcomes count toward promotion.

## Decay & Revalidation

Require three positive rolling validation windows and positive latest Brier
skill versus the expanding base rate. Revalidate every 30 calendar days. A
stale or failing candidate returns to shadow review and never gains order
authority automatically.

## Promotion Blockers

Evidence Tier: completed_daily_ohlcv_shadow_proxy
Evidence Blockers: executable_nbbo_quotes_required, resolved_forward_outcomes_required, kenny_signoff_required

Social-media CAGR and win-rate claims are excluded. The candidate has zero
grade weight outside its own shadow lane until all common promotion gates pass.

## Universe Version

The universe ID, version, membership hash, and membership-as-of date above are
immutable. Any membership or survivorship-policy change creates a new universe
version and a new candidate identity.
