# Preregistration: MES Signed-Flow Absorption Discovery

Date: 2026-07-21
Status: frozen before purchasing or opening the trade-print slice
Execution: research only; no order-routing authority

## Purpose

Direct top-of-book imbalance failed as both continuation and reversal. The next
mechanism uses actual trade prints joined to the existing BBO feed to distinguish
aggressive buying and selling from passive quoted size.

Hypothesis: when aggressive volume is strongly one-sided but price fails to
advance in that direction, passive liquidity is absorbing the flow and a
short-horizon reversal may follow.

## Credit-Only Data Boundary

- Dataset: Databento `GLBX.MDP3`.
- Symbol: continuous volume-front `MES.v.0`.
- Schema: `trades`.
- Period: 2025-10-01 through 2026-01-01.
- Live estimate observed before download: approximately $29.33.
- Verified portal credits before download: $52.82.
- Current portal balance before download: $0.00.
- Download must abort if estimate exceeds $30.00.
- Download must abort unless verified credits exceed estimate by at least $10.
- No card charge is authorized.

This period is discovery-only. It cannot independently promote a strategy.

## Phase A: Outcome-Blind Feature Validation

1. Join each trade print to the latest BBO quote at or before the print.
2. Classify a print as buyer-aggressive when price is at/above the ask and
   seller-aggressive when price is at/below the bid.
3. Resolve midpoint/inside-spread prints using the prior non-zero trade sign;
   leave unresolved prints neutral when no prior sign exists.
4. Aggregate non-overlapping 60-second windows during 09:35-15:30 ET.
5. Compute aggressive buy volume, aggressive sell volume, signed-volume
   imbalance, total aggressive volume, quote coverage, and mid-price
   displacement.
6. Report feature distributions and data quality only. Do not compute forward
   returns, stops, targets, or strategy P&L in Phase A.

Required quality gates:

- At least 40 complete RTH sessions.
- At least 95% of trade prints matched to a prior BBO quote within two seconds.
- At least 90% of matched volume assigned a non-neutral aggressor sign.
- No roll-affected or unavailable-condition sessions included.

## Phase B Boundary

If Phase A passes, freeze one absorption configuration in a second dated
preregistration using only outcome-blind distribution statistics. Only after
that file exists may discovery outcomes be calculated.

Any discovery result still requires at least 30 later chronological
NinjaTrader Sim101 outcomes, realistic fill evidence, zero prop-rule
violations, and human approval. The MES execution task remains disabled.
