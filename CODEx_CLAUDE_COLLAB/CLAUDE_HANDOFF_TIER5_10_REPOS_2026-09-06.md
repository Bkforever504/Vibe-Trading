# CLAUDE HANDOFF — Tier 5: 10-Repo Precision + Execution Upgrade

**Date:** 2026-09-06
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Prior:**
- `CLAUDE_HANDOFF_BASELINE_RECOVERY_COMPLETE_2026-09-06.md` (baseline green, origin clean)
- `CLAUDE_HANDOFF_FAMILY_MAPPING_FIX_2026-09-06.md` (must land before Tier 2 unpauses; Tier 5 is independent and can run in parallel with Tier 2/3/4)
- `CLAUDE_HANDOFF_EDGE_STACK_15_REPOS_2026-09-05.md`
- `CLAUDE_HANDOFF_TIER4_ADDENDUM_10_REPOS_2026-09-05.md`

**Scope:** Ten additional GitHub repositories, none previously integrated, spanning execution realism, vol surface calibration, options data cost reduction, per-trade explainability, GPU-Bayesian regime detection, RL exit-timing (shadow only), alpha decay tracking, and multi-provider chain aggregation.

**Sequence position:** Runs in parallel with existing Tier 2/3/4 tracks. Each repo below is independently gated. No repo is a hard prerequisite for any other Tier 5 repo. **Nautilus (#1) is the deepest lift and should be planned but not started until Tier 4a promotion path clears.**

---

## Non-Negotiable Invariants

- **Every integration lands shadow-only first.** No repo touches live order routing until it clears WS-CV + WS-BOOTSTRAP promotion gate.
- **No new dependency lands without a pinned version in `pyproject.toml` + `uv.lock` entry.**
- **No Codex commit merges to `main` without:** (a) full test suite green (5744+ pass 0 fail), (b) `execution_gate_audit --print passed=True issues=0`, (c) `order_authority_guard violations=0`, (d) `signal_stack_health_report ERROR=0`.
- **Windows AppLocker + numpy/uv pins are load-bearing.** Do not upgrade `numpy`, `pandas`, or `polars` to satisfy a Tier 5 dep unless a fresh handoff documents impact across every existing scanner.
- **Fail-honest on missing data.** If a Tier 5 repo requires a data feed Kenny doesn't have, produce a `not_configured` health status — never fabricate output.
- **Cost gates.** Any repo requiring a paid API (Polygon, OpenBB providers) must land with a monthly-cost estimate + a hard cutoff switch in `config/paid_api_budget.json`.
- **Rollback plan mandatory.** Every PR includes a `docs/rollback/<repo>.md` explaining how to disable the integration without touching working code paths.
- **Repository hygiene invariants from `CLAUDE_HANDOFF_REPO_HYGIENE_2026-09-06.md` still apply.** No `git add -A`, no force-push to main, no secret-file staging.

---

## Priority Matrix

| # | Repo                                                | Category   | Effort   | Risk   | Rollout           |
|---|-----------------------------------------------------|------------|----------|--------|-------------------|
| 1 | nautechsystems/nautilus_trader                      | execution  | 1-month  | medium | Q2                |
| 2 | nkaz001/hftbacktest                                 | analysis   | 1-week   | low    | Month 1           |
| 3 | google/tf-quant-finance                             | signals    | 1-week   | low    | Month 1           |
| 4 | polygon-io/client-python                            | data       | 1-day    | low    | Week 1            |
| 5 | slundberg/shap                                      | analysis   | 1-day    | low    | Week 1            |
| 6 | jmschrei/pomegranate                                | signals    | 1-day    | low    | Week 1            |
| 7 | AI4Finance-Foundation/FinRL-Meta                    | signals    | 1-month  | high   | Shadow-gated only |
| 8 | microsoft/qlib                                      | analysis   | 1-week   | low    | Month 1           |
| 9 | alpaca-py options endpoints                         | data       | trivial  | low    | Week 1            |
| 10| openbb-finance/OpenBB                               | data       | 1-week   | medium | Month 1           |

---

## WS-NAUTILUS — Event-Driven Backtest w/ Live Parity (#1)

**Repo:** `github.com/nautechsystems/nautilus_trader`
**Why:** Fixes "backtest lies vs live fills" for 0DTE. Nanosecond LOB, Rust core, Python API. One engine for backtest / paper / live.
**When:** After Tier 4a promotion path clears. Do NOT start earlier — this is a rewrite of flip_bot execution.

### Files to create
- `agent/execution/nautilus_adapter.py` — wraps Nautilus `TradingNode` with Vibe-Trading order authority guard hooks.
- `agent/execution/nautilus_databento_feed.py` — Databento MBO → Nautilus `OrderBookDeltaData` bridge.
- `agent/execution/nautilus_alpaca_venue.py` — Alpaca broker adapter (paper first).
- `strategies/flip_bot_nautilus.py` — shadow copy of `flip_bot.py` re-implemented as Nautilus `Strategy`.
- `scripts/nautilus_backtest_replay.py` — CLI to replay any 0DTE trading day with Nautilus fill sim.
- `docs/NAUTILUS_MIGRATION_PLAN.md` — 4-phase migration doc (shadow → paper twin → live twin → cutover).
- `agent/tests/test_nautilus_adapter.py` + `test_nautilus_fill_parity.py`.

### Verification
- Shadow phase: 30 trading days where Nautilus + current flip_bot see identical bars and produce identical entry signals (allowed drift: 0 entries).
- Paper twin phase: Nautilus paper vs current Alpaca paper on same signals — fill price delta reported daily, gate on |Δ| ≤ 5 cents on IWM options ≤ $2.
- Live twin only after paper twin runs 20 sessions with no gate-breaking Δ.

### Rollback
- Feature flag `enable_nautilus_execution` in `config/execution.json`. Off = current path. Never on for live until human sign-off.

---

## WS-HFTBACKTEST — Queue-Position Fill Sim from MBO (#2)

**Repo:** `github.com/nkaz001/hftbacktest`
**Why:** Kenny has Databento MBO feed for MES/MNQ + SPY options. hftbacktest gives queue-position-aware simulation of what a passive limit order would have filled at — required to honestly evaluate 0DTE limit-order strategies.
**When:** Month 1 research spike. Not for production — analysis only.

### Files to create
- `scripts/hftbacktest_zerodte_fill_study.py` — replay one 0DTE SPY session, plot expected vs realized fill distribution.
- `scripts/hftbacktest_databento_loader.py` — convert Databento MBO `.dbn.zst` → hftbacktest event format.
- `research/HFTBACKTEST_ZERODTE_FILL_ANALYSIS.md` — findings + recommendations for limit-order aggression.
- `agent/tests/test_hftbacktest_loader.py`.

### Verification
- Loader test round-trips a synthetic MBO fixture with zero deltas.
- Study script produces JSON report with fields: `queue_ahead_median`, `fill_probability_by_price_offset`, `time_to_fill_percentiles`.
- No production code depends on hftbacktest — pure research tool.

### Rollback
- Delete `scripts/hftbacktest_*` + the two other files. No production impact.

---

## WS-TFQF — Vol Surface for Strike Selection (#3)

**Repo:** `github.com/google/tf-quant-finance`
**Alternative:** `vollib/py_vollib_vectorized` + custom SVI/SABR (lighter, no TensorFlow dep).
**Why:** Iron condor wing selection currently uses empirical delta targets. Calibrated SVI/SABR gives model-implied fair-value skew + surface RV/IV analytics → better wing placement, especially on IWM where skew is thin.
**Decision:** Codex evaluates whether TF dep is worth the accuracy gain. Default recommendation: **start with `py_vollib_vectorized` + hand-rolled SVI** (5 free parameters, calibrate per expiry per underlying).

### Files to create
- `agent/vol_surface/svi_calibration.py` — SVI-JW parametrization, calibrate per expiry.
- `agent/vol_surface/vol_surface_service.py` — cached surface for IWM, SPY, QQQ per session; snapshot at 09:35 and 15:45 CT.
- `scripts/vol_surface_shadow.py` — logs (empirical delta, model delta, IV) tuple per condor candidate; runs in shadow before wiring into strike selection.
- `data/vol_surface/<date>_<symbol>_svi.json` — daily calibration snapshot.
- `agent/tests/test_svi_calibration.py`.

### Verification
- Calibration passes SVI arbitrage-free constraints (Roger Lee wings, no calendar arbitrage).
- Shadow log runs 20 sessions before touching iron-condor strike selection.
- Postmortem compares model-implied delta vs empirical delta wing performance — reject integration if realized P/L is not statistically better via bootstrap CI.

### Rollback
- `enable_svi_strike_selection` flag in `config/iwm_options_bot.json`.

---

## WS-POLYGON — Options Chain @ $29/mo (#4)

**Repo:** `github.com/polygon-io/client-python`
**Why:** Databento is priced for tick data, not chain snapshots. Polygon Options Starter is ~$29/mo for 15-min-delayed chain + Greeks at 20 calls/min — 10-20× cheaper than pulling chains from Databento.
**When:** Week 1. This is the cheapest win in Tier 5.

### Files to create
- `agent/data_providers/polygon_options_client.py` — thin wrapper with rate-limit + retry, cache TTL 60s.
- `agent/data_providers/options_chain_router.py` — provider preference: Polygon → Alpaca chain (fallback) → Databento (last resort).
- `config/paid_api_budget.json` — monthly-cost caps + auto-disable when exceeded.
- `scripts/polygon_chain_smoke_test.py` — end-of-day check that Polygon returned expected number of strikes per symbol.
- `agent/tests/test_polygon_options_client.py` (mocked HTTP).

### Environment
- Add `POLYGON_API_KEY` to `agent/.env` (per repo hygiene: never commit `.env`).
- Verify AppLocker allows `polygon-api-client` install path.

### Verification
- Smoke test asserts ≥ 20 strikes per symbol per weekday.
- Cost report generated weekly at `data/paid_api_costs/<week>.json`.
- Cutoff switch verified via unit test: 105% of budget → `RuntimeError` before HTTP call.

### Rollback
- `preferred_options_chain_provider` in `config/options_bot.json` = `databento` reverts.

---

## WS-SHAP — Per-Trade Decision Explanations (#5)

**Repo:** `github.com/slundberg/shap`
**Why:** Postmortems currently list which signals fired. SHAP quantifies each signal's *contribution* to the score → "IV_rank contributed +0.42, market_force contributed −0.18, HMM_regime +0.31." Feeds directly into Discord alerts + `closed_trade_postmortem.py`.

### Files to create
- `agent/analytics/shap_explainer.py` — wraps SHAP TreeExplainer (assuming any tree-based scorer) + KernelExplainer (fallback for arbitrary python scoring functions).
- `agent/analytics/signal_contribution_ledger.py` — writes per-alert SHAP values to `data/shap_contributions.jsonl`.
- Modify `agent/notifier.py` — Discord alert appends top-3 contributors when SHAP snapshot exists.
- Modify `scripts/closed_trade_postmortem.py` — adds SHAP contribution timeline for entry + exit.
- `agent/tests/test_shap_explainer.py`.

### Verification
- Contribution ledger row schema: `{"alert_id", "generated_at", "top_positive": [{"feature", "value", "shap"}, ...], "top_negative": [...], "baseline"}`.
- Discord alert augmentation is behind flag `shap_alerts_enabled` — default off until 5 days of shadow output reviewed.
- Postmortem before/after diff on 10 closed trades — check no output rot.

### Rollback
- Flag off = alerts revert to prior format; ledger keeps writing (harmless).

---

## WS-POMEGRANATE — GPU HMM + Bayesian Nets (#6)

**Repo:** `github.com/jmschrei/pomegranate`
**Why:** Current HMM regime scanner uses `hmmlearn` EM-only fit. Pomegranate offers Bayesian inference, GPU acceleration, and mixture emissions. Drop-in API for HMM; unlocks Bayesian net regime posteriors + variational inference.

### Files to create
- `agent/regime/pomegranate_hmm.py` — HMM with same interface as current hmmlearn wrapper (same input DataFrame, same `RegimeSnapshot` output).
- `scripts/hmm_regime_scanner_pomegranate_shadow.py` — dual-write shadow scanner (writes to `data/hmm_regime_pomegranate.jsonl`) for 20 sessions.
- `research/HMM_POMEGRANATE_VS_HMMLEARN.md` — comparison after shadow window.
- `agent/tests/test_pomegranate_hmm.py`.

### Verification
- Shadow shows correlation ≥ 0.85 between hmmlearn regime posteriors and pomegranate posteriors on same input.
- Any regime divergence > 20% of sessions → escalate for human review before switching primary.
- Convergence test: 100 synthetic sessions with known ground truth — pomegranate posterior median accuracy must beat hmmlearn.

### Rollback
- `hmm_backend` flag in `config/regime.json`; default remains `hmmlearn` until shadow window closes.

---

## WS-FINRL — RL Exit Timing (Shadow-Only) (#7)

**Repo:** `github.com/AI4Finance-Foundation/FinRL-Meta`
**Why:** Kenny's flip bot ratchet exit is rule-based. RL exit policy (PPO trained on historical trade tape) *might* beat it. But: RL overfits catastrophically without discipline.
**Non-negotiable:** RL exit lives behind `WS-CV + WS-BOOTSTRAP` — no promotion without passing statistical gate with n ≥ 30 realized trades.

### Files to create
- `agent/rl/finrl_env_flip_exit.py` — Gymnasium env: state = (unrealized_pnl, time_in_trade, current_delta, IV_change, ratchet_watermark), action = {hold, exit_market, exit_limit_close}, reward = P/L delta − transaction cost.
- `agent/rl/train_flip_exit_ppo.py` — PPO training w/ 5-fold CPCV, purge=1 day, embargo=2 days.
- `scripts/flip_bot_rl_exit_shadow.py` — Shadow scanner: logs what RL would have done vs. actual ratchet exit; NEVER submits orders.
- `research/FINRL_EXIT_POLICY_PREREGISTRATION.md` — preregistration doc (hypothesis, promotion threshold, stopping rule).
- `agent/tests/test_finrl_env_flip_exit.py` (env conformance) + `test_finrl_shadow_no_order_submission.py` (guardrail).

### Verification
- Order authority guard test: pytest asserts `agent.rl.*` never imports `AlpacaTradingClient.submit_order`.
- CPCV Deflated Sharpe of RL policy > current ratchet by ≥ 0.5 with 95% bootstrap CI excluding 0 → then and only then propose promotion.
- Shadow log 60 sessions minimum before evaluation.

### Rollback
- Trivial: delete `agent/rl/*` + the shadow scanner. No production code touched.

---

## WS-QLIB — Alpha Decay + Rolling IC (#8)

**Repo:** `github.com/microsoft/qlib`
**Why:** Fills the gap `mlfinlab` leaves for signal aging. Rolling IC (information coefficient), factor half-life, decay detection → tells Kenny when a signal is aging out before P/L craters.
**Scope:** Use only `qlib.contrib.eva` analysis modules; skip qlib's full data pipeline (would collide with existing data providers).

### Files to create
- `agent/analytics/alpha_decay_tracker.py` — computes rolling IC per signal per window (5d, 20d, 60d).
- `agent/analytics/signal_half_life_estimator.py` — exponential decay fit on IC time series.
- `scripts/alpha_decay_report.py` — weekly cron generates `data/alpha_decay/weekly_<date>.md`.
- Modify dashboard `scripts/generate_dashboard.py` — add "Signal Half-Life" panel.
- `agent/tests/test_alpha_decay_tracker.py`.

### Verification
- Half-life estimator tested against 3 synthetic signals with known decay rates.
- Weekly report gates: signals with 20d IC < 0.02 for 3 consecutive weeks flip to `needs_review` in `signal_registry.json`.
- Register Task Scheduler cron `AlphaDecayWeeklyReport` running Sundays 10 AM CT.

### Rollback
- Cron disable + delete new files. Signal registry state persists (harmless).

---

## WS-ALPACAPY-OPTIONS — Free Chain Fallback (#9)

**Repo:** `github.com/alpacahq/alpaca-py` (options chain endpoints, already installed for equity)
**Why:** Kenny already uses alpaca-py for stocks. Options chain endpoints are free w/ existing paper account. Provides fallback tier below Polygon.

### Files to create/modify
- `agent/data_providers/alpaca_options_client.py` — wraps `OptionHistoricalDataClient` and `OptionLatestQuoteRequest`.
- Modify `agent/data_providers/options_chain_router.py` (from WS-POLYGON) — Alpaca as tier-2 fallback.
- `agent/tests/test_alpaca_options_client.py` (mocked).

### Verification
- Fallback test: force Polygon 429 → assert Alpaca returns valid chain within 500ms.
- Cross-provider diff report: 5 sessions of Polygon vs Alpaca chain deltas logged to `data/chain_provider_diff.jsonl`.

### Rollback
- Router config change reverts to Databento-only.

---

## WS-OPENBB — Multi-Provider Chain Aggregator (#10)

**Repo:** `github.com/openbb-finance/OpenBB`
**Why:** OpenBB's options module aggregates CBOE / Tradier / Intrinio chains behind one API. Insurance against any single provider outage.
**Risk:** Heavy dependency footprint; must verify no numpy/pandas collision.

### Files to create
- `agent/data_providers/openbb_options_client.py` — wraps `openbb.derivatives.options.chains` with provider preference chain.
- Modify `config/options_bot.json` — provider-priority list.
- `scripts/openbb_provider_health_check.py` — pings each configured OpenBB provider; runs hourly.
- `agent/tests/test_openbb_options_client.py`.

### Environment
- **Before install:** Codex runs `uv pip install --dry-run openbb-derivatives` and reports every dep bump. If any of {`numpy`, `pandas`, `polars`, `pyarrow`, `pydantic`} would upgrade, **STOP** and open a separate handoff for the dep bump.
- OpenBB has an interactive first-run wizard — install with `OPENBB_ACCEPT_LICENSE=1` to bypass.

### Verification
- Health check ledger: 24h uptime per provider logged to `data/openbb_provider_health.jsonl`.
- Provider-priority failover exercised in test with mocked HTTP.

### Rollback
- Remove OpenBB from `pyproject.toml`, delete new files. Alpaca + Polygon remain as chain sources.

---

## Sequencing (Codex Execution Order)

### Week 1 — Quick Wins (parallelizable, one PR per repo)
- WS-POLYGON (#4) — highest cost-savings ROI.
- WS-SHAP (#5) — analyst delight; zero prod risk.
- WS-POMEGRANATE (#6) — API-compatible drop-in; shadow window only.
- WS-ALPACAPY-OPTIONS (#9) — trivial; pairs with WS-POLYGON.

### Month 1 — Analysis + Vol Surface
- WS-HFTBACKTEST (#2) — research spike, not production.
- WS-TFQF (#3) — start with `py_vollib_vectorized` + hand-rolled SVI; escalate to TF only if hand-rolled fails calibration constraints.
- WS-QLIB (#8) — analysis module only; add half-life dashboard.
- WS-OPENBB (#10) — LAST in the month; dep-collision check must pass first.

### Shadow-Gated (bounded by CV promotion, no month tag)
- WS-FINRL (#7) — 60-session shadow minimum before ANY promotion discussion.

### Q2 — Deep Architectural Lift
- WS-NAUTILUS (#1) — 4-phase migration; do not start until Tier 4a promotion path clears and family mapping fix is live.

---

## Success Gates Per Workstream

Each WS-* above ships to `origin/main` only after:

1. `git status --porcelain=v1` empty.
2. `python -m pytest agent/tests/ -q` — same baseline pass count + new tests pass.
3. `python scripts/execution_gate_audit.py --print` → `passed=True issues=0`.
4. `python scripts/order_authority_guard.py --print` → `violations=0`.
5. `python scripts/signal_stack_health_report.py --no-write` → `ERROR=0`.
6. New Task Scheduler tasks (if any) registered with `StartWhenAvailable=true` per Pattern Grader RCA.
7. Rollback doc committed at `docs/rollback/<repo>.md`.
8. Discord + dashboard changes reviewed in one human-review round.

---

## Cross-Workstream Risks

- **numpy/pandas dep drift.** Tf-Quant-Finance (#3), pomegranate (#6), FinRL-Meta (#7), qlib (#8), OpenBB (#10) all touch the ML deps stack. Codex must dry-run every install and open a separate `WS-DEPBUMP` handoff if any pin moves. Kenny's AppLocker + uv pins are load-bearing.
- **Windows Task Scheduler blast radius.** WS-QLIB adds a weekly task; WS-POMEGRANATE adds a shadow scanner; register with `StartWhenAvailable=true` and `MultipleInstancesPolicy=IgnoreNew` per Pattern Grader RCA (`data/pattern_grader/rca_2026-09-06.md`).
- **Cost blowout.** WS-POLYGON is the only paid dep here. `config/paid_api_budget.json` hard-cutoff is non-negotiable.
- **Shadow-only guarantee for RL.** WS-FINRL (#7) tests must include an import-graph assertion that `agent/rl/*` never imports live order submission modules — pytest fails the PR otherwise.
- **Nautilus migration blast radius.** WS-NAUTILUS (#1) is deferred to Q2 precisely because its migration touches flip_bot execution. Do not begin without a written cutover plan approved by human.

---

## Files Codex Should Read Before Starting

- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_EDGE_STACK_15_REPOS_2026-09-05.md` — architectural principles for OSS integration.
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_TIER4_ADDENDUM_10_REPOS_2026-09-05.md` — dependency + sequencing patterns.
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_BASELINE_RECOVERY_COMPLETE_2026-09-06.md` — verified baseline invariants.
- `data/pattern_grader/rca_2026-09-06.md` — Task Scheduler registration standard.
- `research/signal_registry.json` — canonical signal registry for SHAP + qlib integration.
- `config/signal_families.json` — family taxonomy (blocked pending family-mapping-fix).

---

## Deferred / Explicitly Not in Scope

- **mementum/backtrader** — maintenance-mode; no options-native support.
- **Standalone triple-barrier / meta-labeling** — `mlfinlab.labeling` suffices.
- **hmmlearn upgrade path beyond pomegranate** — jump-diffusion detectors deferred; `ruptures` covers changepoints.
- **Streaming social sentiment** — low ROI vs. microstructure focus; revisit after WS-CV re-evaluation post family-mapping-fix.
- **Custom LOB reconstruction** — hftbacktest uses Databento MBO directly.

---

## Handoff Complete

Codex: pick a workstream from Week 1 or Month 1, open a feature branch (naming: `tier5/ws-<repo>`), execute per the section above, gate through success criteria, open PR. No workstream depends on another within Tier 5 — parallelizable.

**Reminder:** WS-FAMILY-MAPPING-FIX still gates Tier 2. Tier 5 runs in parallel with Tier 2/3/4 tracks; do not treat any Tier 5 PR as unblocking Tier 2.

---

**Signed:** Claude Opus 4.7, 2026-09-06 13:00 CDT
