# Claude → Codex Handoff: Error Reduction Stack + BLSH Bake-Off

**Date:** 2026-09-07
**Branch:** `handoff/error-reduction-stack-2026-09-07`
**Author:** Claude (Opus 4.7)
**Owner (next):** Codex
**Depends on:** clean baseline (per obs 3111, S486)

---

## TL;DR

Adopt three additive OSS projects — **Prefect, Pandera, Hypothesis** — to eliminate the largest observed error classes in the trading system. Then run a three-way **Buy-Low/Sell-High (BLSH) scanner bake-off** (ARPS vs Donchian+Climax vs LightGBM) under the new orchestration. All work is shadow-first, no execution changes.

Phased so each phase ships independently and rolls back cleanly.

---

## Motivation

Session-memory evidence of ongoing error surface:
- **18 systematic Windows Task Scheduler failures** (obs 3095, 3096) — path misconfig, Python/COM interop, no dep graph
- **ShadowSystemHeartbeat circular self-check** (obs 3107, 3108) — observability tasks fail when operations tasks fail
- **293 dirty hygiene entries** (obs S484) — schema drift with no fail-loud contract
- **11 test failures** on baseline recovery (obs S484) — math paths lightly tested
- **Strategy staleness alerts** (obs 3085) — no orchestration-level freshness enforcement

Root causes decompose into:
1. **Orchestration layer**: Windows Task Scheduler lacks retries, dep graphs, structured logs → **Prefect**
2. **Data contracts**: no schema fail-loud between scanners and strategies → **Pandera**
3. **Math correctness**: example-based pytest misses edge cases in sizing/exit math → **Hypothesis**

BLSH bake-off is the payload — designed to be run under the new orchestration once Prefect is in place.

---

## Phase 0 — Merge Baseline Prep (Codex, day 0)

1. Verify branch `handoff/error-reduction-stack-2026-09-07` off current HEAD (`research/cisd-shadow`).
2. Confirm no regressions: `pytest -x -q` on `tests/`. Known-failing tests noted per `vibe-trading-tests` skill.
3. Verify no dirty paths outside `data/flip_exit_policy_comparison_log.jsonl` and `tools/tradingview-mcp` submodule (pre-existing, obs 3078–3080).

Ship: no code changes. Confirmation only.

---

## Phase 1 — Prefect Orchestration (Codex, days 1-3)

### Goal
Migrate the three highest-failing Windows scheduled tasks to Prefect. Prove pattern before wider migration.

### Steps
1. **Install** in a new venv `prefect-venv/` (do not pollute `kronos-venv` or `.agent-reach-venv`):
   ```
   python -m venv .vibe-trading/prefect-venv
   .vibe-trading/prefect-venv/Scripts/activate
   pip install "prefect>=3.0,<4.0"
   ```
2. **Start local server** as a Windows service (or as a Prefect worker started by a single bootstrap task in Windows Task Scheduler — the *only* remaining scheduled task):
   ```
   prefect server start --host 127.0.0.1 --port 4200
   ```
   Persist as `scripts/register_prefect_server_task.ps1`.
3. **Wrap three flows** in `orchestration/flows/`:
   - `shadow_system_heartbeat_flow.py` (wraps existing heartbeat script)
   - `pattern_grader_flow.py` (wraps `scripts/pattern_grader_scanner.py`)
   - `momentum_sweep_flow.py` (wraps `scripts/momentum_sweep_runner.py`)

   Each flow uses `@flow` decorator, `retries=3, retry_delay_seconds=[30, 120, 600]`, `log_prints=True`. Wrap the existing script entrypoint as a `@task`. Do NOT rewrite the script logic — Prefect wraps `subprocess.run()` calls if easier.

4. **Register deployments** with cron matching existing Windows schedules. See existing `.ps1` registrars in `scripts/` for cadences.

5. **Disable** the three corresponding Windows Task Scheduler tasks (do not delete — mark disabled so rollback is one click).

6. **Instrument** — enable Prefect's built-in logging. Point dashboard to `http://127.0.0.1:4200`.

### Acceptance
- 3 flows run on schedule for 48h with zero manual intervention
- Failure injection test: kill a downstream API, verify retry-with-backoff triggers, verify Prefect UI shows the failure
- Windows Task Scheduler success rate for the 3 migrated tasks: N/A (disabled)
- Prefect UI success rate for the 3 flows: ≥ 95%

### Rollback
Re-enable disabled Windows Task Scheduler tasks. Stop Prefect server. No data changes.

---

## Phase 2 — Pandera Data Contracts (Codex, days 4-6)

### Goal
Add schema fail-loud contracts on shared feature fabric + top 10 scanner outputs.

### Steps
1. **Install**:
   ```
   pip install "pandera[pandas]>=0.20"
   ```
2. **Create** `contracts/schemas.py` with `DataFrameModel` classes for:
   - `OHLCVBar` (open, high, low, close, volume, timestamp, ticker)
   - `IVRSnapshot` (ticker, ivr, iv, rv, rv_iv_spread, timestamp)
   - `HMMState` (ticker, state, prob_trend_up, prob_chop, prob_trend_down, timestamp)
   - `BreadthSnapshot` (ts, adv, dec, new_highs, new_lows, mcclellan)
   - `VWAPFrame` (ticker, ts, vwap, upper_band, lower_band, deviation_z)
   - `ScannerOutput` (base — ticker, ts, scanner_id, score, side, features_json)

3. **Decorate** the outputs of the following scanners with `@pa.check_types` or `Schema.validate()` at return:
   - `scripts/pattern_grader_scanner.py`
   - `scripts/gex_scanner.py`
   - `scripts/hmm_regime_scanner.py`
   - `scripts/ivr_scanner.py`
   - `scripts/momentum_edge_ensemble_shadow.py`
   - `scripts/candlestick_context_scanner.py`
   - `scripts/liquidity_sweep_scanner.py`
   - `scripts/market_breadth_uptrend_scanner.py`
   - `scripts/realized_implied_vol_scanner.py`
   - `scripts/relative_volume_scanner.py`

4. **Decorate** inputs of `strategies/flip_bot.py` and `strategies/iwm_options_bot.py` to fail loudly on bad frames. Under existing execution guards — do NOT alter execution flags.

5. **Add tests** in `tests/test_contracts.py` covering each schema with valid + invalid frames.

### Acceptance
- All decorated scanners run without validation errors on 24h of live data
- Injected bad frame (wrong dtype) raises `SchemaError` immediately, is caught by Prefect flow's retry, logged, and does NOT reach `flip_bot` / `iwm_options_bot`
- `pytest tests/test_contracts.py` green

### Rollback
Remove decorators. Schemas remain as documentation.

---

## Phase 3 — Hypothesis Property Tests (Codex, days 7-9)

### Goal
Property tests on math-heavy paths in flip_bot and iwm_options_bot.

### Steps
1. **Install**:
   ```
   pip install "hypothesis>=6.100"
   ```
2. **Add** `tests/test_flip_bot_properties.py`:
   - `test_position_size_never_exceeds_max_contracts`
   - `test_stop_loss_always_below_entry_for_long`
   - `test_ratchet_never_widens`
   - `test_profit_protect_triggers_monotonically`
   - `test_exit_price_respects_bid_ask_spread`

3. **Add** `tests/test_iwm_options_properties.py`:
   - `test_spread_credit_always_positive_for_credit_spread`
   - `test_max_loss_bounded_by_width_minus_credit`
   - `test_greeks_signs_match_side` (long call → positive delta, etc.)
   - `test_liquidity_check_rejects_below_min_oi`

4. **Add** stateful test for order lifecycle in `tests/test_order_lifecycle.py` using `hypothesis.stateful.RuleBasedStateMachine`.

5. **Run** in CI equivalent (add to `pytest` invocation). Default `max_examples=100`; can raise to 1000 for overnight runs.

### Acceptance
- All new property tests pass with `max_examples=200`
- Any failures found are logged in `research/hypothesis_findings_2026-09-XX.md` for triage — do NOT auto-fix strategy math without user approval per policy
- `.hypothesis/` regression database committed so past failures re-tested on every run

### Rollback
Remove new test files. No production code touched.

---

## Phase 4 — BLSH Bake-Off (Codex, days 10-20)

### Goal
Build three candidate Buy-Low/Sell-High scanners under Prefect + Pandera + Hypothesis. Run in shadow, pick winner via statistical gate.

### Design

**Common feature fabric** (`contracts/schemas.py` types):
- Multi-timeframe range position: intraday VWAP z, 5D Donchian %, 20D Donchian %, 60D Donchian %
- Mean-reversion trigger: RSI(2), RSI(14), close vs 20D z-score
- Regime gate: HMM + Hurst + breadth → `trend_up / chop / trend_down`
- Vol context: IVR, RV/IV spread
- Universe: liquid ETFs (SPY, QQQ, IWM, GLD, TLT) + top-50 optionable names by ADV

**Cadence:** 15-min bars during RTH + EOD summary.

**Horizons:** T+1D, T+5D, T+10D forward returns.

**Prediction ledger:** `data/blsh_predictions.parquet` — `ticker, ts, side, score, scanner, horizon, features_hash`.

**Forward-return joiner:** `orchestration/flows/blsh_fwd_return_joiner_flow.py` — runs T+1D, T+5D, T+10D after each prediction, joins realized MFE/MAE and return.

**Statistical gate:** Diebold-Mariano test on excess returns of top-decile picks, min 3-month live-shadow window, Sharpe + hit rate + IR + capacity thresholds.

### Three scanners

**Scanner A — ARPS (`scripts/arps_scanner.py`):**
Adaptive Range-Position Scanner. Weighted composite of range-position + mean-reversion trigger + regime gate + vol context. Weights fit from repo trade ledger (`data/flip-trades.json`, `data/iwm_*.json`) using MFE/MAE at each bucket. Directionality flip: `trend_up` → low-range = pullback buy; `trend_down` → low-range = falling knife (skip).

**Scanner B — Donchian+Climax (`scripts/donchian_climax_scanner.py`):**
Weekly + daily N-day high/low breakouts with volume climax confirmation (volume > 2× 20D avg + wide-range candle). No regime gate. Fades new-highs on climax, buys new-lows on climax.

**Scanner C — LightGBM (`scripts/lgbm_blsh_scanner.py`):**
Gradient boosting on ~40 features from existing scanners + range-position + mean-reversion + vol + regime. Target = sign of forward 5D return. Walk-forward validation (train on 12 months, predict next 1, roll). Drift monitor: KL divergence on feature distributions rolling weekly.

All three emit to same `ScannerOutput` schema (Pandera-validated), scheduled by Prefect, tested with Hypothesis.

### Acceptance
- All three scanners running in shadow for 3 months on Prefect
- Prediction ledger has >= 1000 predictions per scanner
- Statistical gate report: `research/blsh_bakeoff_report_2026-XX-XX.md`
- Winner (or ensemble weights) proposed for promotion via `vibe-trading-signal-governance` gate — **not** wired to execution without user approval

### Rollback
Disable Prefect deployments for the three scanners. Delete or ignore ledger.

---

## Registry Entries (Codex to Add)

`research/signal_registry.json` needs six entries (three tools + three scanners). Registry has malformed JSON in current head — Codex must fix formatting when adding entries, or split into `signal_registry/*.json` files if easier.

Template (`type: "research_intake"`, `execution_enabled: false`):

```json
{
  "id": "prefect_orchestration",
  "name": "Prefect Orchestration Layer",
  "script": "orchestration/flows/",
  "runner": "prefect_server",
  "scheduled_tasks": ["PrefectServerBootstrap"],
  "log_path": "prefect UI",
  "status": "intake_shadow",
  "execution_enabled": false,
  "can_submit_orders": false,
  "can_read_order_history": false,
  "broker_or_venue": "n/a",
  "feeds": ["orchestration_only"],
  "type": "research_intake",
  "notes": "See research/repo_eval_prefect_2026-09-07.md"
}
```

Analogous entries for `pandera_contracts`, `hypothesis_property_tests`, `arps_scanner`, `donchian_climax_scanner`, `lgbm_blsh_scanner`.

---

## Cost / Risk Budget

- Zero broker calls added. All work is shadow.
- No changes to `strategies/flip_bot.py` or `strategies/iwm_options_bot.py` execution paths (only input decorators added in Phase 2).
- Rollback per phase is single-command.
- Codex may branch off `handoff/error-reduction-stack-2026-09-07` for phase branches, but final merge target is user's choice (main or a Tier-6 integration branch).

---

## Explicit Non-Goals

- Not migrating away from Alpaca / Polygon / Databento / TradingView MCP
- Not touching Kalshi weather bot
- Not touching options bot execution logic (only input validation)
- Not adopting nautilus_trader or other engine (deferred, Phase-2 evaluation only)
- Not disabling any existing guards or safety gates

---

## Open Questions For User

1. Prefect Cloud vs self-hosted UI? Default: self-hosted on trading box.
2. Merge target for final integration: `main` directly, or an integration branch?
3. BLSH bake-off duration: 3 months minimum default; extend to 6 if noise-heavy?

Codex may proceed on defaults if user does not respond within 24h of first Phase completion.

---

## Files Added This Handoff

- `research/repo_eval_prefect_2026-09-07.md`
- `research/repo_eval_pandera_2026-09-07.md`
- `research/repo_eval_hypothesis_2026-09-07.md`
- `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-09-07_ERROR_REDUCTION_STACK.md` (this file)

No code changes yet.
