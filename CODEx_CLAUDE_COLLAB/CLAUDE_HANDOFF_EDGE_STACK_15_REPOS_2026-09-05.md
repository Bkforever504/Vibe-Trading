# CLAUDE HANDOFF — Edge Stack Integration (15 OSS Repos)

**Date:** 2026-09-05
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Scope:** Integrate 15 GitHub repos across signal edge, execution, risk, and evaluation rigor to make the trading system profitable.

---

## Session Summary

Deep GitHub scan across three domains (edge/signals, execution/orchestration, ML/backtest) surfaced 15 high-fit OSS repos not already in the Vibe-Trading stack. This handoff sequences them into three tiers of shadow-first integration workstreams. All Tier-1 work must land with `execution_enabled=false`, signal_registry gating, and reconciled outcomes before any live-trading impact.

**Non-negotiable invariants (apply to every workstream):**
- Shadow-only until 10+ reconciled outcomes AND Deflated Sharpe > 0 AND human review.
- Fail-honest: missing data → `status="missing"`, never fabricate OHLCV / NBBO / features.
- All new signals register in `agent/signal_registry.json` with promotion gate metadata.
- No secret in source; use `agent/.env` and rotate on any exposure.
- Budget caps env-gated per external API. Ledger every paid call.
- Restricted permissions on new persistent outputs; human-review flag on any strategy artifact.

---

## Execution Order (Tiers)

**Tier 1 (Week 1-2) — drop-in, high-leverage, zero-cost:**
1. WS-EDGAR — SEC EDGAR 8-K + Form 4 catalyst scanner
2. WS-CV — Purged K-fold + Deflated Sharpe + PSR promotion gate
3. WS-RISK-MATH — Riskfolio-Lib CDaR/EDaR per-strategy drawdown budgets
4. WS-BOOTSTRAP — Block bootstrap confidence intervals on outcomes

**Tier 2 (Week 3-6) — moderate lift, structural upgrade:**
5. WS-PREFECT — Replace Windows Task Scheduler with Prefect flows
6. WS-TASTY — Tastytrade broker adapter for native complex options orders
7. WS-GEX — gammagrid + FlashAlpha 0DTE dealer/gamma regime layer
8. WS-META — mlfinlab meta-labeling over existing signals
9. WS-QUIVER — Quiver alt-data (Congress, WSB, dark-pool)

**Tier 3 (Month 2-3) — heavier, revisit after Tier 1-2 prove ROI:**
10. WS-RISK-CODE — ThePredictiveDev pre-trade risk manager code lift
11. WS-DRIFT — Evidently drift monitor over feature snapshots
12. WS-REGIME — ruptures + BOCPD change-point detection
13. WS-IBKR — ib_async second-broker leg for equity SMART routing
14. WS-OFI — orderflow-metrics OFI/VPIN microstructure signals
15. WS-OPTOPSY — Options-specific backtester audit of IWM bot fills

---

## WS-EDGAR — SEC EDGAR 8-K + Form 4 Catalyst Scanner

**Repo:** https://github.com/dgunning/edgartools (MIT, ~2.7k stars, active)
**Dep:** `pip install edgartools`

**Goal:** Emit shadow signals when watchlist tickers file 8-K events or when insider Form 4 clusters ≥$1M appear.

**Files to create:**
- `agent/shadow_scanners/edgar_catalyst_scanner.py`
- `agent/tests/test_edgar_catalyst_scanner.py`
- `data/edgar_state/last_seen_accession.json` (persistent watermark)
- `docs/EDGAR_CATALYST_SIGNAL.md`

**Files to modify:**
- `agent/signal_registry.json` — add `edgar_8k_watchlist`, `edgar_form4_cluster` entries with `promotion_gate={min_outcomes:10, min_deflated_sharpe:0.0, requires_human_review:true}`
- `scripts/scheduled_scanner.py` — hook scanner into 60s polling loop with fail-honest wrapping
- `scripts/generate_dashboard.py` — add EDGAR panel (last poll ts, filings 24h, missing status)

**Invariants:**
- Poll interval ≥60s (SEC courtesy limits).
- Persist last-seen accession per ticker; never re-emit.
- Fail-honest: EDGAR unreachable → signal status="missing", not stale-live.
- No execution wiring — signal only, `execution_enabled=false` at registry.

**Tests (min):**
- `test_edgar_watermark_persistence` — accession watermark survives restart.
- `test_edgar_missing_on_network_error` — emits status="missing" not stale data.
- `test_form4_cluster_threshold` — cluster ≥$1M triggers, single filing does not.
- `test_no_reemit_on_seen_accession` — dedupe within 24h window.

**Verification:**
```powershell
python scripts/signal_stack_health_report.py --no-write
# → edgar_8k_watchlist status=OK OR MISSING (never STALE)
python -m pytest agent/tests/test_edgar_catalyst_scanner.py -q
# → all pass
```

**Success gate:** Signal emits during 5 trading days without ERROR status; ≥1 test 8-K captured.

---

## WS-CV — Purged K-fold + Deflated Sharpe + PSR Promotion Gate

**Repos:**
- https://github.com/eslazarev/purged-cross-validation (drop-in)
- https://github.com/esvhd/pypbo (PBO + Deflated Sharpe)
- https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio (reference)

**Dep:** `pip install purged-cross-validation pypbo`

**Goal:** Replace qualitative "10 outcomes + human review" promotion gate with statistical CPCV + Deflated Sharpe accounting for trial count.

**Files to create:**
- `agent/governance/statistical_gate.py` — CPCV runner, Deflated Sharpe calc, PSR calc, PBO calc
- `agent/tests/test_statistical_gate.py`
- `docs/STATISTICAL_PROMOTION_GATE.md`

**Files to modify:**
- `agent/signal_registry.json` — extend schema: `promotion_gate.min_deflated_sharpe`, `promotion_gate.max_pbo`, `promotion_gate.min_psr`
- `scripts/reconcile_outcomes.py` (or equivalent) — invoke `statistical_gate.evaluate(signal_id)` on every outcome batch write
- `scripts/generate_dashboard.py` — Signal Governance panel: show DSR, PSR, PBO per signal alongside outcome count
- All existing promoted signals — re-evaluate through new gate, flag downgrades to needs_review

**Invariants:**
- Gate is fail-closed: missing outcome data → cannot promote.
- DSR accounts for N trials attempted (not just N outcomes on the survivor).
- PBO calc uses combinatorial CPCV, not simple k-fold.
- Existing promoted signals do NOT auto-demote; they enter re-evaluation queue with human review.

**Tests (min):**
- `test_cpcv_purged_embargo_no_leakage` — synthetic data with known leakage yields inflated Sharpe; purged CV yields correct.
- `test_deflated_sharpe_penalizes_trials` — 10 trials → DSR < Sharpe of best.
- `test_gate_fail_closed_on_missing_outcomes` — <10 outcomes → gate returns not_ready, never approves.
- `test_pbo_detects_overfit` — deliberately overfit strategy → PBO > 0.5.
- `test_existing_signals_reevaluated_not_dropped` — demoted signals enter review queue.

**Verification:**
```powershell
python -m pytest agent/tests/test_statistical_gate.py -q
python scripts/reconcile_outcomes.py --dry-run --verbose
# → Every currently promoted signal reports DSR/PSR/PBO
python scripts/generate_dashboard.py
# → Governance panel shows new stats
```

**Success gate:** All 88 existing tests still pass. Every signal in registry has DSR calculated. At least one currently promoted signal is flagged for re-review (expected — old gate was permissive).

---

## WS-RISK-MATH — Riskfolio-Lib CDaR/EDaR Per-Strategy Drawdown Budgets

**Repo:** https://github.com/dcajasn/Riskfolio-Lib (drop-in)
**Dep:** `pip install Riskfolio-Lib`

**Goal:** Replace flat max-contract caps with drawdown-aware per-strategy budgets (Conditional Drawdown at Risk, Entropic DaR).

**Files to create:**
- `agent/safety_gates/drawdown_budget.py` — computes rolling CDaR/EDaR per strategy, returns allowed size multiplier ∈ [0.0, 1.0]
- `agent/tests/test_drawdown_budget.py`
- `config/drawdown_budgets.json` — per-strategy limits (flip_bot, iwm_options_bot, etc.)
- `docs/DRAWDOWN_BUDGET.md`

**Files to modify:**
- `agent/iwm_options_bot.py` — pre-order size gate: `size = base_size * drawdown_budget.multiplier(strategy_id)`
- `agent/flip_bot.py` (or equivalent) — same gate
- `scripts/execution_gate_audit.py` — new check: no strategy exceeds its CDaR budget
- `scripts/generate_dashboard.py` — Risk panel: current CDaR / EDaR / budget utilization per strategy

**Invariants:**
- Budget = 0.0 → strategy is halted, not merely throttled. Kill switch semantics preserved.
- Rolling window ≥60 trading days; if <30 days of history → budget = 0.5 (conservative default).
- Recovery: budget scales back up as drawdown heals; no manual reset required.
- Global portfolio-level CDaR overrides per-strategy budgets (portfolio drawdown wins).

**Tests (min):**
- `test_budget_zero_halts_new_orders` — CDaR breach → next order rejected pre-broker.
- `test_conservative_default_on_thin_history` — <30 days → multiplier=0.5.
- `test_recovery_scaling` — synthetic drawdown recovery → multiplier increases.
- `test_portfolio_override` — per-strategy OK but portfolio CDaR breached → all strategies halt.

**Verification:**
```powershell
python -m pytest agent/tests/test_drawdown_budget.py -q
python scripts/execution_gate_audit.py --print
# → issues=0, all strategies within budget
```

**Success gate:** Backtest against historical outcomes shows drawdown reduction ≥20% with expectancy loss ≤5%.

---

## WS-BOOTSTRAP — Block Bootstrap Confidence Intervals on Outcomes

**Repos:**
- https://github.com/bashtage/arch (GARCH + stationary/circular/moving block bootstrap)
- https://github.com/astrogilda/tsbootstrap (generalized block, local block, GARCH residual)

**Dep:** `pip install arch tsbootstrap`

**Goal:** Attach 95% CI to every outcome metric (expectancy, win rate, Sharpe) in postmortems and needs-review reports.

**Files to create:**
- `agent/analytics/outcome_bootstrap.py`
- `agent/tests/test_outcome_bootstrap.py`
- `docs/BOOTSTRAP_CI.md`

**Files to modify:**
- Existing postmortem generator — every metric shows `value [CI_low, CI_high]`
- `scripts/generate_dashboard.py` — trade table + P/L view render CI where N ≥ 20
- Daily outcome reviewer — flag signals whose CI_low crosses zero as `low_confidence`

**Invariants:**
- Block size auto-selected via `arch.bootstrap.optimal_block_length`.
- Bootstrap iterations ≥1000; fail-closed on insufficient samples (N<20 → no CI, display "insufficient data").
- CI displayed as absolute values, not percent, to prevent misreading.

**Tests (min):**
- `test_ci_widens_with_lower_n` — N=20 CI wider than N=200.
- `test_zero_crossing_flags_low_confidence` — expectancy CI includes 0 → flag raised.
- `test_optimal_block_length_ge_1` — never returns 0 or negative.

**Verification:**
```powershell
python -m pytest agent/tests/test_outcome_bootstrap.py -q
```

**Success gate:** Latest daily outcome review shows CI on every signal with N≥20.

---

## WS-PREFECT — Replace Windows Task Scheduler + PS Runners

**Repo:** https://github.com/PrefectHQ/prefect (moderate lift, huge infra unlock)
**Dep:** `pip install prefect`

**Goal:** Migrate scheduled_scanner + reconcile jobs + postmortem gen + dashboard gen into Prefect flows for observability, retry semantics, and API-overload backoff.

**Files to create:**
- `agent/orchestration/flows/scheduled_scanner_flow.py`
- `agent/orchestration/flows/reconcile_flow.py`
- `agent/orchestration/flows/dashboard_flow.py`
- `agent/orchestration/flows/postmortem_flow.py`
- `agent/orchestration/deployments.py` — Prefect deployment definitions with cron schedules matching current Windows Task Scheduler
- `scripts/prefect_start_local.ps1` — start local Prefect server + agent
- `docs/PREFECT_MIGRATION.md`

**Files to modify:**
- Existing PS runner scripts — mark as deprecated; leave in place until Prefect flows verified 5 trading days
- README run instructions

**Invariants:**
- All external API tasks (Alpaca, Databento, EDGAR, Anthropic if used) wrap in `@task(retries=5, retry_delay_seconds=exponential_backoff(2))`.
- Every flow logs `flow_run_id` alongside signal outputs for traceability.
- No flow can start if `execution_enabled` env changed within last 60s without explicit `PREFECT_ALLOW_FRESH_ENV=true`.
- Windows Task Scheduler remains parallel-active for first 5 days; disable only after Prefect proves parity.

**Tests (min):**
- `test_task_retry_on_transient_error` — mocked 529/503 → retries then succeeds.
- `test_flow_run_id_propagates_to_signal` — signal outputs include originating flow_run_id.
- `test_fresh_env_change_blocks_flow` — env toggled → flow refuses without override flag.

**Verification:**
```powershell
python -m pytest agent/tests/test_prefect_flows.py -q
prefect deployment ls
# → 4 deployments registered
```

**Success gate:** 5 consecutive trading days where Prefect flow outputs match Windows Task Scheduler output byte-for-byte (or diff is explainable).

---

## WS-TASTY — Tastytrade Broker Adapter for Complex Options Orders

**Repo:** https://github.com/tastyware/tastytrade (~600 stars, active)
**Dep:** `pip install tastytrade`

**Goal:** Second broker leg for IWM spreads/condors with native OTOCO/OCO/PAIRS complex orders. Fixes Alpaca leg-in/leg-out slippage on multi-leg tickets.

**Files to create:**
- `agent/brokers/tastytrade_adapter.py` — implements same interface as existing Alpaca adapter
- `agent/brokers/base.py` — extract broker interface if not already abstract
- `agent/tests/test_tastytrade_adapter.py`
- `docs/BROKER_ADAPTER_TASTYTRADE.md`

**Files to modify:**
- `agent/iwm_options_bot.py` — read `IWM_BROKER=alpaca|tastytrade` from env; default alpaca
- `agent/.env.example` — add `TASTYTRADE_USERNAME`, `TASTYTRADE_PASSWORD`, `IWM_BROKER=alpaca`
- `scripts/execution_gate_audit.py` — audit both brokers if configured

**Invariants:**
- Adapter interface parity: any bot must work identically under either adapter.
- Complex orders (OTOCO/OCO) go through Tastytrade only; if Alpaca selected, fall back to sequential leg-in with existing safeguards.
- Credentials never logged; adapter refuses to start if any credential env is empty.
- Paper-first: `TASTYTRADE_ENV=cert` mandatory until 20+ verified fills.

**Tests (min):**
- `test_tastytrade_credentials_required` — missing env → adapter raises on init, never silently degrades.
- `test_otoco_order_construction` — leg dataclasses match expected schema.
- `test_env_switches_broker` — env var flips broker selection.
- `test_paper_only_default` — cert env is default; live requires explicit opt-in.

**Verification:**
```powershell
python -m pytest agent/tests/test_tastytrade_adapter.py -q
python -c "from agent.brokers.tastytrade_adapter import TastytradeAdapter; a = TastytradeAdapter(); print(a.health())"
# → paper-mode OK
```

**Success gate:** 20 paper-mode multi-leg orders through Tastytrade with 100% fill parity to intended structure.

---

## WS-GEX — gammagrid + FlashAlpha 0DTE Dealer/Gamma Regime

**Repos:**
- https://github.com/gammagrid/gammagrid (AGPL-3.0, Docker sidecar) — dealer GEX, max pain
- https://github.com/FlashAlpha-lab/0dte-options-analytics — 0DTE pin risk, gamma regime, expected move
- https://github.com/Matteo-Ferrara/gex-tracker (backup, MIT)

**Goal:** Feed dealer GEX + 0DTE pin-risk into IWM bot as sizing gate.

**Files to create:**
- `agent/shadow_scanners/dealer_gex_scanner.py` — pulls GEX + max pain for SPY/IWM/QQQ
- `agent/shadow_scanners/zero_dte_regime.py` — pin risk, gamma regime classifier
- `agent/tests/test_dealer_gex.py`
- `agent/tests/test_zero_dte_regime.py`
- `docker-compose.gammagrid.yml` — sidecar with restricted network exposure
- `docs/DEALER_GEX_LAYER.md`

**Files to modify:**
- `agent/iwm_options_bot.py` — new sizing gate: `size *= gex_regime.size_multiplier(ticker, spot)` (shrink inside positive-gamma pin zones, expand in negative-gamma).
- `agent/signal_registry.json` — `dealer_gex_regime`, `zero_dte_pin_risk` with promotion gate
- `scripts/generate_dashboard.py` — Dealer Positioning panel (GEX zero-flip, max pain, current pin distance)

**Invariants:**
- AGPL licensing note in `NOTICE.md`; ensure it does not contaminate closed portions of repo.
- Docker sidecar bind-mount is read-only for host repo; container has no write access to bot code.
- Fail-honest: sidecar down → sizing multiplier defaults to 1.0 with `status="missing"`, never 0 or >1.
- Cost: verify data source cost cap (some GEX libs pull from paid feeds).

**Tests (min):**
- `test_gex_multiplier_bounded` — never returns <0 or >2.
- `test_missing_gex_defaults_to_one` — sidecar unreachable → size = base_size.
- `test_pin_risk_shrinks_size` — synthetic pin scenario → multiplier < 1.
- `test_negative_gamma_expands_size` — synthetic neg-gamma → multiplier ≥ 1.

**Success gate:** 5 trading days of shadow GEX signals; IWM bot P/L in shadow mode with GEX gate ≥ P/L without gate (paired comparison).

---

## WS-META — mlfinlab Meta-Labeling Over Existing Signals

**Repo:** https://github.com/hudson-and-thames/mlfinlab (moderate lift, mind license — check current status; some modules paywalled)
**Dep:** `pip install mlfinlab` (or vendor the open modules; verify license on install)

**Goal:** Train a secondary classifier per existing signal to predict *when to trust it*. Composes with governance, does not replace it.

**Files to create:**
- `agent/ml/meta_labeler.py` — triple-barrier labeler + secondary model (sklearn LogReg or GBM)
- `agent/ml/train_meta_labeler.py` — offline training script per signal
- `agent/tests/test_meta_labeler.py`
- `data/meta_labels/<signal_id>_model.pkl` (persisted, gitignored)
- `docs/META_LABELING.md`

**Files to modify:**
- `agent/signal_registry.json` — per-signal `meta_labeler_enabled: bool`, `min_confidence: float`
- Signal emit path — if meta enabled: pull confidence, gate emission on `confidence >= min_confidence`
- Postmortem — record raw signal outcome vs meta-gated outcome for comparison

**Invariants:**
- Meta-labeler is opt-in per signal, off by default.
- Model trained via WS-CV purged CPCV only (no leakage).
- Every meta decision logged with model version hash for auditability.
- Fail-honest: model file missing or unloadable → meta disabled with WARN, signal emits raw.

**Tests (min):**
- `test_meta_disabled_by_default` — new signals do not gate on meta.
- `test_meta_low_confidence_blocks_emission` — synthetic low-confidence → no emit.
- `test_model_hash_logged` — every gated decision includes model version.
- `test_missing_model_fails_open_to_raw_signal` — model file absent → raw signal still emits.

**Success gate:** For any signal with meta enabled, meta-gated outcomes must beat raw outcomes on Deflated Sharpe over ≥30 reconciled outcomes.

---

## WS-QUIVER — Quiver Alt-Data (Congress, WSB, Dark-Pool)

**Repo:** https://github.com/Quiver-Quantitative/python-api
**Dep:** `pip install quiverquant` (API key required — free tier first, ledger every call)

**Goal:** Congress trades, WSB velocity, dark-pool short volume, 13F changes as independent shadow signals.

**Files to create:**
- `agent/shadow_scanners/quiver_congress_scanner.py`
- `agent/shadow_scanners/quiver_wsb_velocity.py`
- `agent/shadow_scanners/quiver_dark_pool_scanner.py`
- `agent/tests/test_quiver_scanners.py`
- `data/quiver_call_ledger.jsonl` (append-only, restricted permissions)
- `docs/QUIVER_ALT_DATA.md`

**Files to modify:**
- `agent/.env.example` — `QUIVER_API_KEY=`, `QUIVER_DAILY_CALL_CAP=200`
- `agent/signal_registry.json` — 4 new shadow signals with independent promotion gates
- `scripts/generate_dashboard.py` — Alt-Data panel: call count, cost, last update, missing status

**Invariants:**
- Every call to Quiver API written to ledger with (timestamp, endpoint, ticker, cost_units).
- Daily call cap enforced pre-request; over-cap → status="missing" for remainder of day.
- No emit without ≥2-source confirmation (e.g., Congress buy + WSB velocity spike).
- Each of 4 signals promotes independently through statistical gate.

**Tests (min):**
- `test_call_cap_enforced` — 201st call blocked, status=missing.
- `test_ledger_write_on_every_call` — mocked call → ledger row appended.
- `test_two_source_rule_for_emission` — single-source alert → no emit.
- `test_missing_key_no_boot_error` — empty API key → scanner starts, reports missing, does not crash.

**Success gate:** 10 trading days shadow log; each of 4 signals accumulates outcomes for eventual promotion gate evaluation.

---

## WS-RISK-CODE — ThePredictiveDev Pre-Trade Risk Manager Code Lift

**Repo:** https://github.com/ThePredictiveDev/Automated-Financial-Market-Trading-System

**Goal:** Cherry-pick pre-trade risk manager pattern (per-owner drawdown, volatility halts, leverage caps) as reference for hardening existing safety_gates.

**Files to create:**
- `agent/safety_gates/pre_trade_risk_manager.py`
- `agent/tests/test_pre_trade_risk_manager.py`
- `docs/PRE_TRADE_RISK_MANAGER.md`

**Files to modify:**
- All bots — every order pre-check flows through `pre_trade_risk_manager.check(order)`; rejection is fail-closed.
- `scripts/execution_gate_audit.py` — new check: pre-trade manager reachable and returning decisions.

**Invariants:**
- Manager is single choke-point; no bot bypass permitted.
- Every rejection logged with reason code.
- Combines with WS-RISK-MATH budget: order rejected if EITHER gate fails.

**Tests:** Standard fail-closed + auditability tests.

---

## WS-DRIFT — Evidently Drift Monitor Over Feature Snapshots

**Repo:** https://github.com/evidentlyai/evidently

**Goal:** Catch feature-distribution drift before postmortems do.

**Files to create:**
- `agent/monitoring/drift_monitor.py`
- `agent/tests/test_drift_monitor.py`

**Files to modify:**
- Prefect nightly flow — run drift report over last 30 days of feature snapshots, emit alert if drift score > threshold.
- Dashboard — Drift panel per feature.

---

## WS-REGIME — ruptures + BOCPD Non-Parametric Regime Break Detection

**Repos:**
- https://github.com/deepcharles/ruptures (offline)
- https://github.com/hildensia/bayesian_changepoint_detection (online)

**Goal:** Orthogonal signal to existing HMM regime; catches breaks HMM misses.

**Files to create:**
- `agent/regime/change_point.py`
- `agent/tests/test_change_point.py`

**Files to modify:**
- Market condition map — combine HMM + BOCPD; disagreement → warn on dashboard.

---

## WS-IBKR — ib_async Second-Broker Leg for Equity SMART Routing

**Repo:** https://github.com/ib-api-reloaded/ib_async

**Goal:** Third broker (Alpaca + Tastytrade + IBKR) for equity fills using SMART routing.

**Files to create:**
- `agent/brokers/ibkr_adapter.py`
- `agent/tests/test_ibkr_adapter.py`

**Files to modify:**
- `agent/.env.example` — IBKR TWS/Gateway credentials.

---

## WS-OFI — orderflow-metrics OFI/VPIN Microstructure Signals

**Repo:** https://github.com/twowaymind/orderflow-metrics (pip)

**Goal:** OFI, VPIN, trade-sign classification from Databento MBP feed as microstructure alpha.

**Files to create:**
- `agent/shadow_scanners/ofi_vpin_scanner.py`
- `agent/tests/test_ofi_vpin.py`

---

## WS-OPTOPSY — Options-Specific Backtester Audit

**Repo:** https://github.com/goldspanlabs/optopsy

**Goal:** Independent audit of IWM bot outcome logic with per-leg delta targeting.

**Files to create:**
- `research/optopsy_iwm_audit.py`
- `docs/IWM_OPTOPSY_AUDIT.md` (report of any discrepancies)

---

## Skip List — Do Not Integrate

- **TradingAgents (Tauric Research)** — LLM agents, documented 22% DD / 7% return. Only via Astra shadow-critic if experimented with.
- **FinRL** — RL trading, no credible live validation.
- **FinGPT** — no reliability evidence.
- **vectorbt for options P/L** — idealized fills lie about IWM options economics. Use for param sweep only, never trust its Sharpe.
- **Qlib whole platform** — rewrite territory. Cherry-pick Alpha-158 expression lib only if signal-mining phase demands it.
- **nautilus_trader, lumibot** — architecturally superior engine rewrites. Defer until Tier 1-2 prove ROI.
- **Paid sec-api.io** — edgartools polling covers 95% at $0.
- **Polymarket arbitrage** — lag too long for intraday day trading.

---

## API Overload Mitigation (Ambient Fix)

- Anthropic API 529 hit during parallel research spawns. Codex: cap concurrent Agent/subagent spawns at ≤2 across the repo's tooling.
- Prefect task retries with exponential backoff (WS-PREFECT) is the durable fix — every external API call gets it for free once migrated.
- Move heavy research/backtest jobs to Prefect nightly batches, not intra-session synchronous calls.
- Add `@task(retries=5, retry_delay_seconds=[2,4,8,16,32])` decorator to every Anthropic/Alpaca/Databento/EDGAR call.

---

## End-of-Session Verification Checklist (run after each workstream)

```powershell
python scripts/signal_stack_health_report.py --no-write
# → OK=38+ (grows with each workstream), STALE=0, MISSING allowed, ERROR=0

python scripts/execution_gate_audit.py --print
# → passed=True issues=0

python -m pytest agent/tests/ -q
# → all pass, count grows per workstream

python scripts/generate_dashboard.py
# → Wrote ~/.vibe-trading/dashboard.html
```

---

## Open Positions / Active Risks

- No open live positions (paper only).
- Existing signal registry entries continue to reconcile on old gate until WS-CV lands; do not disable old gate until statistical gate proven parity or better.
- API credentials rotated per prior session (obs #3016). Confirm no new leaks in workstream commits — pre-commit hook must scan every diff.

---

## Next Session Priority Action for Codex

**Start with WS-EDGAR** (highest ROI, lowest risk, zero cost, drop-in). Deliver:
1. Scanner code + tests
2. Registry entry with statistical gate placeholder
3. Dashboard panel
4. 5-day shadow run kickoff

Then **WS-CV** to install the statistical promotion gate before any Tier-2 workstream produces signals that would gate through it.

---

## Known Caveats / Deferred

- WS-META (mlfinlab): verify license status of desired modules before install; some Hudson & Thames modules are paywalled as of last check.
- WS-GEX (gammagrid): AGPL-3.0 — sidecar-only architecture avoids contamination but ensure NOTICE.md is added.
- WS-TASTY: paper-first, 20 fills before any live consideration; live requires explicit human sign-off.
- WS-IBKR: requires TWS or Gateway running; add health check to dashboard.
- Astra AI shadow-critic integration (prior handoff) is independent of this stack; sequence Astra AFTER WS-CV so DSR governs Astra's veto decisions.

---

## Handoff Complete

Codex: acknowledge in BRIDGE, start with WS-EDGAR. Any blocker → open a BRIDGE message rather than deviate from invariants. Ship shadow-only, gate through statistics, promote through outcomes.
