# Codex Handoff: MES Causal Impact-Replenishment Divergence - 2026-08-10

## Executive State

Codex created and preregistered one differentiated MES microstructure
challenger, then tested it without a parameter grid. It failed. Do not describe
it as an edge, a market-beating strategy, or a globally novel invention.

No order was submitted. Execution remains disabled.

## Strategy Created

Name: Causal Impact-Replenishment Divergence (CIRD)

Files:

- `research/MES_CAUSAL_IMPACT_REVERSAL_PREREGISTRATION_2026-08-10.md`
- `research/mes_causal_impact_reversal_lab.py`
- `scripts/run_mes_causal_impact_reversal_lab.ps1`
- `agent/tests/test_mes_causal_impact_reversal_lab.py`
- `data/mes_causal_impact_reversal_results.json`
- `research/MES_CAUSAL_IMPACT_REVERSAL_RESULTS_2026-08-10.md`

Mechanism:

1. Convert one-second BBO changes into Cont-style order-flow imbalance.
2. Fit a causal trailing 30-minute, zero-intercept flow/impact coefficient.
3. Find a 2.5-sigma flow shock whose realized impact is no more than 25% of
   the trailing model's expected move.
4. Require the ending quote to replenish against the shock.
5. Wait ten seconds for a one-tick opposing price confirmation.
6. Enter opposite the shock at the executable BBO; use a 12-tick target,
   8-tick stop, and five-minute time exit.

This combines price-impact failure and liquidity resiliency. It differs from
the repository's failed fixed quote-imbalance and fixed absorption rules, but
global novelty is not asserted.

## Exact Historical Result

Artifact: `data/mes_causal_impact_reversal_results.json`

- Period: 2024-01-02 to 2026-07-17.
- Complete eligible sessions: 618.
- Development / selection / final: 370 / 124 / 124 sessions.
- Confirmed candidates across all sessions: 1.
- Development: 1 trade, -$7.48 base, -$12.46 stressed.
- Development gate: failed.
- Selection opened: false.
- Final opened: false.
- Topstep diagnostic run: false.
- Promotion ready: false.
- Orders submitted: 0.

The result is consumed-history diagnostic evidence, not independent
validation. The exact specification is permanently rejected on these dates.

## Data Artifacts

The run produced two reusable, outcome-blind caches:

- `data/databento/mes_bbo_valid_1s_2024_2026.parquet` (~127 MB)
- `data/databento/mes_bbo_ofi_30s_2024_2026.parquet` (~16 MB)

The first contains one valid last BBO per second after roll/quality/session
exclusions. The second contains causal 30-second Cont OFI and quote features.
They have no execution authority.

## Claude's Next Assignment

Do not loosen, sweep, optimize, or rerun CIRD on the consumed 2024-2026 period.
Do not invent a target win rate or search until something passes.

The next legitimate research objective is a forward-only Depth Resiliency
Residual using genuinely new TopstepX/ProjectX quote, trade, and DOM data:

1. Keep `execution_enabled: false` and `can_submit_orders: false`.
2. Resolve the data-access decision with Kenny. Topstep currently requires an
   active paid Combine for a Practice account and separately paid API access;
   do not purchase either without explicit authorization.
3. If access is authorized, run the existing recorder manually on the personal
   device. Do not install a scheduler until the smoke test and redaction audit
   pass.
4. Enforce every gate in
   `research/TOPSTEPX_MICROSTRUCTURE_DATA_PROTOCOL_2026-08-09.md` for at least
   20 complete RTH sessions.
5. Before opening any future return, build an outcome-blind feasibility report
   for event-based OFI, top-five depth replenishment, cancellation/addition
   asymmetry, spread recovery time, and impact residual distributions.
6. Preregister at most three economically distinct variants. Freeze event
   buckets, thresholds, entry delay, executable fills, target/stop/time exit,
   costs, familywise alpha, chronology, and promotion gates.
7. Require positive expectancy after doubled costs, PF >= 1.20, adequate trade
   count, subperiod stability, circular-block confidence >= 0.95, and exact
   Topstep simulation before any forward shadow promotion.
8. Historical success, if any, can enable only a frozen forward shadow. Require
   at least 30 later trades before reconsidering Practice execution.
9. Run focused tests and the full repository suite. Preserve unrelated dirty
   worktree changes. Write a new dated handoff with exact results and whether
   any order was sent.

If paid data access is declined, stop this lane. Do not substitute synthetic
DOM, social-media claims, or further price-pattern grids and call them evidence.

## Verification

- New CIRD unit suite: 7 passed.
- Focused CIRD, prior microstructure, and Topstep suite: 30 passed.
- Search-grid regression plus CIRD suite: 16 passed.
- Full repository suite on final code: 4,521 passed, 4 skipped, 4 existing
  deprecation warnings in 230.59 seconds.
- One stale pre-existing MES search assertion was updated to include the
  already-present 45- and 60-minute CRB/delta ranges.
- No relevant Python process remained after verification.

## Safety Invariants

- No live, Combine, or Practice orders.
- No paid purchase without explicit user authorization at action time.
- No credential values in logs, tests, reports, or chat.
- No strategy promotion from consumed history.
- No size increase to compensate for absent expectancy.
