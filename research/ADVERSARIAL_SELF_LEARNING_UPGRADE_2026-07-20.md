# Adversarial Self-Learning Upgrade

## Objective

Make every bot learn from completed evidence without allowing a bot to approve
its own strategy, rewrite production rules, or increase capital exposure.

## Loop

1. Actual and shadow outcomes produce postmortems.
2. Behavior mismatches and failed adversarial checks become immutable mistake events.
3. Stable pattern IDs reveal repeated mistakes across runs and bots.
4. Repeated patterns nominate one shadow-only challenger.
5. Challengers are preregistered in the edge-trial ledger.
6. Independent manifests attack look-ahead, parity, outlier reliance, costs,
   parameter stability, regimes, walk-forward durability, bootstrap uncertainty,
   and multiple-testing-adjusted Sharpe.
7. The strategy verifier blocks promotion when the audit is missing or failed,
   or when repeated high-severity mistakes remain unresolved.
8. Human review is still required. No component may submit orders.

## Safety Contract

- Learning is append-only and preserves losing evidence.
- Production parameters remain frozen.
- Automatic changes are limited to research nominations.
- A challenger cannot replace its champion until it passes independent forward evidence.
- Confidence measures evidence completeness and robustness, not guaranteed profit.

## Current State

The framework is operational, but existing strategies do not automatically
inherit a passing audit. Each needs a complete raw-evidence manifest. Until then,
the new gate correctly reports that promotion evidence is incomplete.
