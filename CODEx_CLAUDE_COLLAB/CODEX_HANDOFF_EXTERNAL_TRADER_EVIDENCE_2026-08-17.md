# Claude Code Handoff: External Trader Evidence

Date: 2026-08-17

## Objective

Use public trader and algorithm teachings without letting screenshots, opaque records, books, or videos become unvalidated bot rules.

## Implemented

1. `research/external_strategy_sources.json`
   - Twelve governed sources.
   - Scores rule completeness, independent verification, cost realism, holdout quality, point-in-time data, licensing, and complete loss history.
   - Maps each source to a bot, permitted use, and existing artifact.

2. `scripts/external_strategy_evidence.py`
   - Validates evidence values and implementation artifacts.
   - Classifies sources as benchmark, shadow-replication eligible, process control, engineering reference, hypothesis-only, discovery-only, required caveat, or rejected.
   - Always emits `execution_enabled: false`, `can_submit_orders: false`, and `automatic_promotion: false`.

3. `research/pyquant_strategy_family_lab.py`
   - Added `smooth_momentum_proxy_weights`.
   - Monthly, positive 12-1 momentum, top-six shortlist, select two highest positive-day-share assets, equal weight, one-day execution lag.
   - Explicitly labeled as a proxy, not Alpha Architect QMOM.

4. `scripts/profitability_evidence_review.py`
   - Includes the external-source audit in the combined diagnostic bundle.
   - Existing profitability blockers are unchanged.

5. Tests
   - `agent/tests/test_external_strategy_evidence.py`
   - Expanded `agent/tests/test_pyquant_strategy_family_lab.py`

## Results

- Targeted tests: 13 passed.
- Source audit: 12 sources, 0 missing declared artifacts.
- Shadow-replication eligible: AQR trend and Jegadeesh/Titman momentum.
- Cboe PutWrite: accepted benchmark only.
- Alpha Architect smooth-momentum concept: hypothesis-only proxy.
- Milkman ATR spread: hypothesis-only pending exact historical option quotes.
- Darwinex/Sersan: discovery-only because entries are opaque.
- Social P&L screenshots: rejected as edge evidence.
- No orders submitted; no broker or task configuration changed.

New proxy result, 2007-2026:

- CAGR 12.23%
- Sharpe 0.744
- Max drawdown 32.35%
- Selection CAGR 8.76%
- Final CAGR 21.14%
- Double-cost CAGR 11.79%
- Passed shadow-review gate, but remains blocked because drawdown is worse than the current canonical weekly strategy and no forward sample exists.

Current options evidence remains weak:

- 16 resolved outcomes
- 5 active resolution days
- -$569 aggregate executable P&L before fees
- All existing promotion blockers remain active

## Next Work

Build one preregistered challenger, not another broad search:

1. Combine `smooth_momentum_proxy_weights` with the existing breadth-scaled BIL overlay.
2. Freeze the combined rules before running.
3. Compare against both SPY and `existing_canonical_12m_top2_weekly` on development/selection/final windows and doubled costs.
4. Add a monthly forward shadow ledger with source timestamps, selected symbols, intended weights, next-open proxy, and resolution.
5. Require 12 resolved rotations for an initial review and 24 for a paper-promotion discussion.
6. Do not alter production bots, account sizing, schedulers, or execution flags.

## Verification Commands

```powershell
python -m pytest agent\tests\test_external_strategy_evidence.py agent\tests\test_pyquant_strategy_family_lab.py agent\tests\test_profitability_evidence_review.py -q
python scripts\external_strategy_evidence.py --print
python research\pyquant_strategy_family_lab.py --print
python scripts\profitability_evidence_review.py
```

The repo virtual environment is blocked by Windows Application Control on this machine. Use the system `python` command for verification. `uv run` also currently fails while resolving the malformed upstream `zigzag==0.3.2` package metadata.
