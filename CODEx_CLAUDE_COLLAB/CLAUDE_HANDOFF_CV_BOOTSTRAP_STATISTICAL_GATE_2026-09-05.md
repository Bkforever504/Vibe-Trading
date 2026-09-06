# CLAUDE HANDOFF — Statistical Promotion Gate (WS-CV + WS-BOOTSTRAP)

**Date:** 2026-09-05
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Prior:** `CLAUDE_HANDOFF_EDGE_STACK_15_REPOS_2026-09-05.md` (parent spec)
**Scope:** Ship WS-CV + WS-BOOTSTRAP in one PR. Both consume `arch` and share governance/panel wiring; bundling avoids dep churn and dashboard rework.

---

## Session Summary

WS-EDGAR NBBO hardening + WS-TRACE end-to-end tracing shipped clean (114+25+116 tests, zero fabrication, honest 157-alert gap, forward-instrumentation live). Next: install the statistical promotion gate that must precede any Tier-2 signal (mlfinlab meta, dealer GEX, Quiver alt-data) because those signals promote through DSR/PBO. Bundle WS-BOOTSTRAP because (a) it shares the `arch` dependency, (b) it feeds the 30-paired-sample latency CI already committed to in WS-TRACE, and (c) postmortem CIs land in the same dashboard panel work.

---

## Non-Negotiable Invariants (both workstreams)

- Fail-closed: insufficient outcomes / trials → gate returns `not_ready`, never `approved`.
- No auto-demotion of existing promoted signals. They enter `needs_review` with new stats attached.
- Every metric persisted to disk includes: sample count `n`, trial count `t`, block size `b`, iterations `k`, model/library version hash.
- Bootstrap iterations ≥ 1000. Block size via `arch.bootstrap.optimal_block_length` (never hard-coded).
- Trial count for DSR must include ALL signals attempted historically, not just current registry entries (or the correction collapses).
- No new secret; no new external API; no execution wiring changes.
- Runs entirely offline against the outcomes DB / reconciliation ledger.

---

## Dependencies

```
pip install purged-cross-validation pypbo arch tsbootstrap
```

Pin versions in `requirements.txt`. If any pin conflicts with existing numpy/scipy, resolve by pinning down the new libs — do NOT bump numpy (breaks Windows AppLocker per repo memory).

---

## WS-CV — Purged K-fold + Deflated Sharpe + PSR + PBO

### Files to create

- `agent/governance/statistical_gate.py`
  - `class StatisticalGate`:
    - `evaluate(signal_id) -> GateDecision` where `GateDecision` includes `{status, n_outcomes, n_trials, sharpe, deflated_sharpe, psr, pbo, block_size, model_version, reason}`
    - Pulls outcomes from existing reconciliation store; fails-closed if store unreachable.
    - CPCV via `purged_cross_validation.CombinatorialPurgedKFold` with embargo = 1 bar.
    - DSR via `pypbo.deflated_sharpe_ratio(sharpe, n_trials, sr_variance)`; `n_trials` sourced from `agent/governance/trial_ledger.py` (see below).
    - PBO via `pypbo.pbo(returns_matrix)` over CPCV splits; matrix built from per-fold in-sample vs out-sample Sharpe.
    - PSR via `pypbo.probabilistic_sharpe_ratio(sharpe, benchmark=0, n)`.
    - Model version = SHA of module source (`hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()[:12]`).
- `agent/governance/trial_ledger.py`
  - Append-only JSONL at `data/governance/trial_ledger.jsonl` (restricted perms).
  - `record_trial(signal_id, hypothesis_hash, timestamp)` invoked once at signal registration.
  - `count_trials(family_key)` returns lifetime count for DSR denominator; families defined in `config/signal_families.json` so related signals share trial pool.
  - Idempotent on `(signal_id, hypothesis_hash)`.
- `config/signal_families.json`
  - Groups existing signals into families (e.g., `momentum`, `mean_reversion`, `orderflow`, `catalyst`). Family membership determines whose trial count feeds DSR.
- `agent/tests/test_statistical_gate.py`
- `agent/tests/test_trial_ledger.py`
- `docs/STATISTICAL_PROMOTION_GATE.md` — user-facing explanation of DSR/PSR/PBO, why they replace "10 outcomes + human review", and how to interpret the dashboard panel.

### Files to modify

- `agent/signal_registry.json`
  - Extend `promotion_gate` schema:
    ```json
    {
      "min_outcomes": 30,
      "min_deflated_sharpe": 0.0,
      "min_psr": 0.95,
      "max_pbo": 0.5,
      "family_key": "orderflow",
      "requires_human_review": true
    }
    ```
  - Existing entries: preserve current values, add `family_key`, `min_deflated_sharpe: null` (means old gate still applies until re-evaluated).
- `scripts/reconcile_outcomes.py` (or whichever job writes reconciled outcomes)
  - After every outcome batch write, call `StatisticalGate.evaluate(signal_id)` for every touched signal.
  - Result persisted to `data/governance/gate_history/<signal_id>.jsonl` (append-only).
- `scripts/execution_gate_audit.py`
  - New check: every currently promoted signal has a `gate_history` entry within last 24h. If missing → audit fails.
- `scripts/generate_dashboard.py`
  - Add **Signal Governance** panel:
    - Table: signal_id, family, n_outcomes, sharpe, DSR, PSR, PBO, status, last_evaluation_ts.
    - Signals with `status=needs_review` highlighted.
    - "Insufficient data" label wherever n < min_outcomes.
- Existing promoted signals — bulk re-evaluate once via one-shot script `scripts/reevaluate_existing_promoted_signals.py`. Output = `data/governance/reevaluation_report_<date>.md`. No auto-demotion; every downgrade candidate enters `needs_review` queue.

### Tests (minimum required)

- `test_cpcv_purged_embargo_no_leakage` — synthetic series w/ known 5-bar lookahead leakage. Naive k-fold reports Sharpe > 2.0; purged CPCV with embargo=1 reports Sharpe ≈ true value.
- `test_deflated_sharpe_penalizes_trials` — same Sharpe, trials=1 → DSR ≈ Sharpe; trials=100 → DSR meaningfully lower.
- `test_pbo_flags_overfit` — synthetic strategy hand-tuned to in-sample → PBO > 0.5.
- `test_gate_fail_closed_on_missing_outcomes` — n_outcomes=5 while min=30 → status=`not_ready`, reason cites shortfall.
- `test_gate_fail_closed_on_missing_trial_ledger` — ledger file absent → gate returns error status, does not synthesize `n_trials=1`.
- `test_no_auto_demotion` — existing signal with new metrics below threshold → `needs_review`, promotion flag unchanged in registry.
- `test_family_key_shares_trial_pool` — two signals in same family → DSR uses combined family trial count.
- `test_model_version_hash_persists` — every gate_history row includes the module SHA at eval time.

### Verification

```powershell
python -m pytest agent/tests/test_statistical_gate.py agent/tests/test_trial_ledger.py -q
python scripts/reevaluate_existing_promoted_signals.py --dry-run
# → produces markdown report; confirms no writes in dry-run
python scripts/reevaluate_existing_promoted_signals.py
# → writes gate_history for every existing signal
python scripts/execution_gate_audit.py --print
# → passed=True, every promoted signal has gate_history within 24h
python scripts/generate_dashboard.py
# → Governance panel populated
```

### Success gate for WS-CV

- All existing tests + new tests pass.
- 100% of currently promoted signals have gate_history entry.
- Re-evaluation report exists and identifies any signals now failing DSR/PBO. Report reviewed by human before any registry mutation.

---

## WS-BOOTSTRAP — Block Bootstrap CIs on Outcomes and Latency

### Files to create

- `agent/analytics/outcome_bootstrap.py`
  - `def bootstrap_ci(series, statistic_fn, iterations=1000, ci=0.95) -> BootstrapResult`
  - `BootstrapResult` = `{point, ci_low, ci_high, n, block_size, iterations}`
  - Block size via `arch.bootstrap.optimal_block_length(series)['stationary']`.
  - Statistic functions provided: `mean_expectancy`, `win_rate`, `sharpe`, `max_drawdown`, `latency_p50`, `latency_p95`.
  - Refuses to run when `n < 20`; returns `{point: None, reason: "insufficient_data"}`.
- `agent/analytics/paired_bootstrap.py`
  - `def paired_diff_ci(series_a, series_b, iterations=1000, ci=0.95)` for the latency baseline vs new-pipeline paired test committed to in WS-TRACE.
  - Requires same length; refuses on mismatch.
  - Returns `{diff_mean, diff_ci_low, diff_ci_high, excludes_zero}`.
- `agent/tests/test_outcome_bootstrap.py`
- `agent/tests/test_paired_bootstrap.py`
- `docs/BOOTSTRAP_CI.md` — reader guide: what CI means, why block bootstrap for time series, when to trust vs distrust.

### Files to modify

- Existing postmortem generator (identify via `grep -rn "postmortem" agent/ scripts/`)
  - Every metric renders as `value [ci_low, ci_high]` when `n >= 20`; else `value (n=<n> — insufficient data)`.
- Daily outcome reviewer
  - Signals where `expectancy_ci_low <= 0` → flag `low_confidence`.
  - Flag surfaced in dashboard needs_review queue.
- `scripts/generate_dashboard.py`
  - Extend Signal Governance panel: every metric column shows CI where `n >= 20`.
  - New **Latency Proof** panel: paired-bootstrap result of new-pipeline vs baseline (once 30 paired samples exist per WS-TRACE contract). Until then: "insufficient paired samples: `n`/30".
- Latency measurement pipeline (WS-TRACE outputs)
  - After each new alert with full trace fields, append to `data/latency_pairs.jsonl` with `{trace_id, baseline_latency_ms, new_latency_ms}`.
  - Baseline latency source: from stored pre-instrumentation p50 if defensible, else refuse to claim improvement (invariant from WS-TRACE holds).

### Tests (minimum required)

- `test_ci_widens_with_lower_n` — n=20 → wider CI than n=200 for identical distribution.
- `test_insufficient_data_returns_none` — n=19 → point=None, reason set; no fabricated CI.
- `test_optimal_block_length_bounds` — always integer ≥ 1.
- `test_paired_diff_excludes_zero_flag` — synthetic paired series with real 10ms improvement → `excludes_zero=True`.
- `test_paired_diff_includes_zero_flag` — noise-only → `excludes_zero=False`.
- `test_length_mismatch_raises` — paired series different lengths → ValueError, never partial run.
- `test_iterations_at_least_1000_persisted` — every result records `iterations=1000` in metadata.

### Verification

```powershell
python -m pytest agent/tests/test_outcome_bootstrap.py agent/tests/test_paired_bootstrap.py -q
python scripts/generate_dashboard.py
# → Governance panel shows CIs where n>=20; Latency Proof panel shows insufficient sample notice
```

### Success gate for WS-BOOTSTRAP

- All new tests pass.
- Postmortem output visibly renders `[ci_low, ci_high]` for every mature signal.
- Latency Proof panel exists and honestly reports insufficient paired samples until forward instrumentation accumulates 30.

---

## Combined End-of-Session Verification

```powershell
python scripts/signal_stack_health_report.py --no-write
# → OK count unchanged or higher; STALE=0; ERROR=0

python scripts/execution_gate_audit.py --print
# → passed=True; issues=0

python -m pytest agent/tests/ -q
# → all pass; count = previous + new WS-CV/BOOTSTRAP tests

python scripts/generate_dashboard.py
# → Governance panel populated; Latency Proof panel present
```

---

## Files Changed Summary Template (for Codex handoff back)

```
CREATED:
  agent/governance/statistical_gate.py
  agent/governance/trial_ledger.py
  agent/analytics/outcome_bootstrap.py
  agent/analytics/paired_bootstrap.py
  agent/tests/test_statistical_gate.py
  agent/tests/test_trial_ledger.py
  agent/tests/test_outcome_bootstrap.py
  agent/tests/test_paired_bootstrap.py
  config/signal_families.json
  scripts/reevaluate_existing_promoted_signals.py
  docs/STATISTICAL_PROMOTION_GATE.md
  docs/BOOTSTRAP_CI.md
  data/governance/trial_ledger.jsonl (empty init)
  data/governance/gate_history/ (dir)
  data/latency_pairs.jsonl (empty init)

MODIFIED:
  agent/signal_registry.json          (schema extension, family_key backfill)
  scripts/reconcile_outcomes.py       (gate hook)
  scripts/execution_gate_audit.py     (24h freshness check)
  scripts/generate_dashboard.py       (Governance + Latency Proof panels)
  requirements.txt                    (new pins)
  (postmortem generator wherever it lives — grep first)
  (daily outcome reviewer wherever it lives — grep first)
```

---

## Open Positions / Active Risks

- No live positions.
- WS-TRACE forward-instrumentation now producing new alert records; ensure new gate + bootstrap DO NOT depend on any of the 157 pre-instrumentation alerts having full trace fields. Both must handle `null` trace fields gracefully.
- Existing signal promotion decisions remain in force during rollout. `needs_review` queue is advisory until human sign-off per invariant.

---

## Next Session Priority After This Ships

Per parent handoff Tier 2 order:
1. **WS-PREFECT** — replace Windows Task Scheduler; also solves API-overload via retry decorators.
2. **WS-TASTY** — Tastytrade adapter for complex options fills.
3. **WS-GEX** — dealer gamma sizing gate for IWM bot.
4. **WS-META** — mlfinlab meta-labeling (must gate through WS-CV — sequencing rationale).
5. **WS-QUIVER** — alt-data shadow scanners.

Do NOT start Tier 2 workstreams until WS-CV + WS-BOOTSTRAP re-evaluation report has been reviewed by human. Reason: Tier-2 signals will attempt promotion through the new gate, and any config/threshold miscalibration surfaces on the re-eval report first.

---

## Known Caveats / Deferred

- **Trial ledger backfill** — historical trials count as `1` per registered signal by default because we lack per-hypothesis trial records pre-ledger. This UNDER-counts trials and OVER-states DSR for legacy signals. Explicit backfill note in `data/governance/trial_ledger.jsonl` header comment; do NOT silently pretend counts are accurate. Family-level counts remain honest going forward.
- **Family key assignments** in `config/signal_families.json` require human review before merging; misgrouping distorts DSR sharing.
- **`pypbo` and `purged-cross-validation`** — verify latest version compatibility with current numpy/scipy pins. If breakage, prefer vendoring the relevant module over bumping numpy.
- **Baseline latency** — if no defensible pre-instrumentation p50 exists, the paired-bootstrap panel forever shows "no baseline available" rather than fabricate one. This is correct behavior.

---

## Handoff Complete

Codex: single PR covering both workstreams. Acknowledge in BRIDGE, ship, run verification, return receipt with test counts + gate audit + reevaluation report path. Do not merge auto-demotions.
