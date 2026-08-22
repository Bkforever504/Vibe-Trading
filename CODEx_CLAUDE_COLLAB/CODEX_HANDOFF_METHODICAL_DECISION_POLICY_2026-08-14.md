# Codex Handoff: Methodical Decision Policy - 2026-08-14

## Objective

Replace additive signal accumulation with a staged paper decision contract while preserving
strict execution safety and continued evidence collection.

## Implemented Contract

`strategies/methodical_decision_policy.py` separates:

1. authority and portfolio safety;
2. directional thesis;
3. fresh price trigger;
4. independent current confirmations;
5. conflicts and abstention;
6. GARCH size reduction;
7. executable order handling, which remains in the existing Flip bot guards.

Primary paper eligibility requires a passed entry-evidence gate and at least one current external
confirmation with no directional conflicts. Incomplete or conflicting alpha context is routed to
one-contract paper exploration rather than being mislabeled as high confidence. Hard safety or
missing-trigger failures stand aside.

Decision capture is enabled by default. Enforcement is deliberately off until the new cohorts have
forward evidence. To run the paper experiment, set
`FLIP_METHODICAL_DECISION_ENFORCEMENT_ENABLED=true`; live authority remains unavailable.

## Authority Boundaries

- Heat maps, inferred GEX, unsigned public options surfaces, social narratives, Kronos, and
  unvalidated TimesFM forecasts cannot cast directional execution votes.
- The policy cannot call a broker or submit an order.
- The policy has no live-capital authority.
- Existing quote freshness, OPRA authority, spread, executable-EV, reconciliation, daily-loss,
  and kill-switch gates remain unchanged.

## Claude Review Tasks

1. Verify that primary versus exploration cohorts are recorded in every completed lifecycle.
2. After 30 distinct dates, compare primary, exploration, and rejected counterfactual outcomes
   after fees and executable prices.
3. Promote or remove each confirmation source by preregistered incremental expectancy, not win
   rate alone.
4. Do not let any forecast, news sentiment, heatmap, or social source gain execution authority
   without point-in-time calibration and ablation evidence.
