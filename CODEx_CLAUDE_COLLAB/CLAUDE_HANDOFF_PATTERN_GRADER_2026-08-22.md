# CLAUDE → CODEX HANDOFF — Pattern Grader & Setup Recognition Engine

**Date:** 2026-08-22
**Author:** Claude (session prep for Codex)
**Repo:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
**Scope:** All instruments (MES/ES, IWM, equities, 0DTE SPX), all timeframes (1m → daily)
**Non-negotiable safety posture:** Advisory + shadow first. A-grade auto-execute is a Phase 3 gated milestone — do NOT wire order authority in Phase 1 or 2.

---

## 0. Goal

Give the dashboard a first-class **Pattern Grader** that:

1. Detects the full spectrum of trading setups (classical, candlestick, volume, SMC/ICT, Wyckoff, order flow, options-flow, session/regime) with **machine-precise geometric rules**.
2. Grades each detected setup **A / B / C / D** using a weighted confluence rubric.
3. Publishes grades to the dashboard **read-only** (Phase 1), with **auto-block on D-grade** shadow logging (Phase 2), and eventually **auto-execute on A-grade** after 30+ days of paper validation (Phase 3, safety review required).
4. Feeds an outcome-tracking loop so grades are continuously validated against realized R:R.

Grade thresholds (see §5): **A ≥ 85**, **B 70–84**, **C 55–69**, **D < 55**.

---

## 1. Deliverables Summary

| # | Deliverable | Path | Phase |
|---|---|---|---|
| D1 | Pattern taxonomy JSON | `research/pattern_taxonomy.json` | 1 |
| D2 | Swing / market-structure primitives | `agent/src/tools/market_structure.py` (extend existing) | 1 |
| D3 | Pattern detectors (11 families) | `agent/src/tools/pattern_detectors/*.py` | 1 |
| D4 | Volume Profile + aVWAP engine | `agent/src/tools/volume_profile.py`, `anchored_vwap.py` | 1 |
| D5 | Regime detector composite | `agent/src/tools/regime_composite.py` | 1 |
| D6 | Pattern grade scorer | `agent/src/tools/pattern_grade_scorer.py` | 1 |
| D7 | Pattern grader scanner (shadow) | `scripts/pattern_grader_scanner.py` | 1 |
| D8 | Nightly aggregator + report | `scripts/pattern_grader_report.py` → `~/.vibe-trading/reports/pattern-grader-grades.json` | 1 |
| D9 | Dashboard panel wire-up | edit `scripts/generate_dashboard.py` (REPORTS dict + render fn) | 1 |
| D10 | Signal registry entries | edit `research/signal_registry.json` (shadow-only, `can_submit_orders=false`) | 1 |
| D11 | Outcome resolver | `scripts/pattern_grader_outcome_resolver.py` | 2 |
| D12 | Grade quality scorecard | `scripts/pattern_grader_scorecard.py` → dashboard panel | 2 |
| D13 | Auto-block on D-grade advisory | dashboard Advisory tab pill: "Block D-grade entries" | 2 |
| D14 | A-grade auto-execute policy | `agent/src/policies/pattern_grade_execution_policy.py` + registry flip | 3 (Kenny approval req'd) |
| D15 | Test suite | `agent/tests/test_pattern_*.py` (12+ test files) | 1–3 |

---

## 2. Existing Infrastructure — Reuse Points (from repo audit)

**Detectors to extend, not replace:**

| Need | Existing module | Extension |
|---|---|---|
| Swing points / MS | `agent/src/skills/smc/example_signal_engine.py:22-100` (wraps `smartmoneyconcepts` lib) | Add ATR filter (Grimes: reject swings < 0.5×ATR) + k=3 fractal option for 1m |
| BOS / CHoCH / FVG | `agent/src/skills/smc/example_signal_engine.py:71-100` | Add displacement-candle qualifier + "true BOS" flag |
| Candlestick classifier | `agent/src/tools/pattern_tool.py:55-90` | Add context gates (trend + RVOL) + confirmation-bar requirement |
| Classical patterns (H&S, DT/DB, triangle, broadening) | `agent/src/tools/pattern_tool.py:155-282` | Add volume divergence checks + measured-move target calc |
| Liquidity sweep | `scripts/liquidity_sweep_scanner.py:71-100` | Reuse JSONL log schema for pattern grader ledger |
| Market structure catalog | `scripts/market_structure_intelligence.py:16-38` (PATTERN_CATALOG w/ 15+ patterns, role tags) | Extend catalog w/ Wyckoff phases, ICT arrays, order-flow signatures |
| Candlestick context shadow log | `scripts/candlestick_context_scanner.py` + `data/candlestick_context_log.jsonl` | Copy JSONL template for pattern grader ledger |
| Signal registry + audit | `research/signal_registry.json` + `scripts/execution_gate_audit.py:22-100` | Add new entries; audit must continue to pass |
| Dashboard | `scripts/generate_dashboard.py:36-66` (REPORTS dict) | Add `"pattern_grades"` panel; render heatmap + tables |
| Shadow logger template | `scripts/smc_shadow_logger.py:40-68` | Copy schema; add pattern_id + grade + outcome_5m/15m/60m |

**Data feeds available:** Alpaca IEX (real-time), Databento MES/options parquet (historical + intraday), yfinance (research), Polygon (registered but no active client). No footprint/DOM feed yet — Phase 1 order-flow detectors must be **approximated from OHLCV+delta proxies** (up-tick vs down-tick volume). Footprint/tick engine deferred to Phase 2 pending Databento or Rithmic feed decision.

---

## 3. Pattern Taxonomy — What the Grader Recognizes

Master JSON goes to `research/pattern_taxonomy.json`. Every entry has this schema:

```json
{
  "id": "bull_flag_5m",
  "family": "classical_continuation",
  "timeframes": ["1m","5m","15m","1h"],
  "regime_fit": ["trending"],
  "base_rate": 0.68,
  "avg_r_multiple": 2.1,
  "detection_rule": "impulse ≥ 3 bars & net move ≥ 3*ATR14 & RVOL ≥ 2; consolidation 5-20 bars, pullback ≤ 38.2% Fib of impulse, channel slope in [-0.3,0]*ATR, V_flag/V_pole < 0.6",
  "entry_trigger": "close above upper channel + 0.1*ATR & RVOL ≥ 1.5",
  "stop": "below flag low OR below 50% Fib of pole",
  "target_t1": "breakout + 0.5 * length(pole)",
  "target_t2": "breakout + 1.0 * length(pole)",
  "invalidation": "close below flag low",
  "anti_pattern": "pullback > 50% Fib OR ATR rising in flag OR flag > 20 bars",
  "sources": ["Bulkowski Encyclopedia 3rd ed."],
  "notes_2026": "Currently the top-performing intraday continuation setup per practitioner surveys (Tradeify/QuantVPS 2026)."
}
```

**Complete family list (11):**

### Family 1 — Classical Chart Patterns (Bulkowski-graded)
`head_shoulders_top`, `inverse_head_shoulders`, `double_top`, `double_bottom`, `triple_top`, `triple_bottom`, `ascending_triangle`, `descending_triangle`, `symmetrical_triangle`, `rising_wedge`, `falling_wedge`, `bull_flag`, `bear_flag`, `pennant`, `cup_handle`, `rounded_bottom`, `rectangle_range`

### Family 2 — Candlestick Patterns (context-gated)
`bull_engulfing`, `bear_engulfing`, `hammer`, `hanging_man`, `shooting_star`, `inverted_hammer`, `morning_star`, `evening_star`, `three_white_soldiers`, `three_black_crows`, `piercing`, `dark_cloud`, `tweezer_top`, `tweezer_bottom`, `marubozu`, `long_legged_doji`, `dragonfly_doji`, `gravestone_doji`, `bull_harami`, `bear_harami`

### Family 3 — Volume Profile
`poc_rejection`, `poc_acceptance`, `hvn_bounce`, `lvn_traversal`, `value_area_break`, `vpoc_migration`

### Family 4 — Anchored VWAP
`avwap_mean_revert_2sigma`, `avwap_trend_hold`, `avwap_reclaim`, `avwap_gap_fill`

### Family 5 — Session / Opening Range
`orb_5m`, `orb_15m`, `orb_30m`, `orb_60m`, `ib_extension`, `ib_failure`, `first_hour_breakout`, `midday_drift_fade`, `moc_imbalance`, `gap_and_go`, `gap_fade`

### Family 6 — SMC / ICT
`bullish_order_block`, `bearish_order_block`, `breaker_block`, `mitigation_block`, `fvg_bisi`, `fvg_sibi`, `ote_zone`, `inducement`, `premium_short`, `discount_long`, `silver_bullet_am`, `silver_bullet_pm`, `london_sweep_ny_reverse`

### Family 7 — Wyckoff
`accumulation_spring`, `distribution_utad`, `phase_c_test`, `sos_breakout`, `lps_pullback`, `psy_climax`, `selling_climax`, `buying_climax`

### Family 8 — Order Flow (OHLCV-approximated for Phase 1)
`delta_divergence`, `cumulative_delta_break`, `climax_volume_reversal`, `rvol_breakout`, `volume_dry_up_pre_breakout`
*(Phase 2 additions when tick feed available: `stacked_imbalance`, `absorption`, `iceberg`, `sweep`, `dom_spoof`)*

### Family 9 — Options Flow
`gex_flip`, `pos_gamma_pin`, `neg_gamma_trend`, `zero_dte_pin_risk`, `uoa_flow`, `iv_crush_setup`, `pc_ratio_extreme`

### Family 10 — Liquidity Structure
`equal_highs_sweep`, `equal_lows_sweep`, `trendline_liquidity_run`, `hod_lod_sweep`, `prior_day_extreme_sweep`

### Family 11 — Multi-Timeframe Combos (composite / meta)
`mtf_bull_flag_1h_up_d_above_50ma`, `mtf_ihs_15m_d_basing`, `mtf_htf_ob_ltf_ote`, `mtf_orb_vwap_align`

Detection rules per entry (geometric, quantitative, machine-implementable) are provided in the accompanying **research pack** files (Codex should write these as it builds detectors):
- `research/pattern_detection_rules_classical.md`
- `research/pattern_detection_rules_smc_wyckoff.md`
- `research/pattern_detection_rules_orderflow_options.md`

Full text of those rule packs is embedded below in §Appendix A/B/C — copy into those files verbatim as first step.

---

## 4. Detection Pipeline Architecture

```
                ┌───────────────────────────────────────────┐
                │ 1. OHLCV Loader (per instrument × TF)     │
                │    Alpaca / Databento / yfinance          │
                └───────────────┬───────────────────────────┘
                                ▼
                ┌───────────────────────────────────────────┐
                │ 2. Market Structure Primitives            │
                │    swings, BOS, CHoCH, sweeps, disp candle│
                └───────────────┬───────────────────────────┘
                                ▼
                ┌───────────────────────────────────────────┐
                │ 3. Family Detectors (parallel)            │
                │    - Classical      - Candlesticks        │
                │    - Volume Profile - aVWAP               │
                │    - Session/ORB    - SMC/ICT             │
                │    - Wyckoff        - Order flow proxy    │
                │    - Options flow   - Liquidity           │
                └───────────────┬───────────────────────────┘
                                ▼
                ┌───────────────────────────────────────────┐
                │ 4. Regime Composite Filter                │
                │    HMM state + Hurst + RV/IV + GEX        │
                │    → per-family trust weight              │
                └───────────────┬───────────────────────────┘
                                ▼
                ┌───────────────────────────────────────────┐
                │ 5. MTF Alignment Scorer                   │
                │    0.5*strength + 0.3*higherTF_agree      │
                │    + 0.2*lowerTF_agree                    │
                └───────────────┬───────────────────────────┘
                                ▼
                ┌───────────────────────────────────────────┐
                │ 6. Pattern Grade Scorer  →  A/B/C/D       │
                └───────────────┬───────────────────────────┘
                                ▼
                ┌───────────────────────────────────────────┐
                │ 7. Shadow JSONL Log + Nightly Aggregator  │
                │    data/pattern_grader_log.jsonl          │
                └───────────────┬───────────────────────────┘
                                ▼
                ┌───────────────────────────────────────────┐
                │ 8. Dashboard Panel (read-only)            │
                └───────────────────────────────────────────┘
```

---

## 5. Grading Rubric — 0–100 Composite

Score is the weighted sum of six components. Each component is normalized to [0, 100]. Weights sum to 1.0.

| # | Component | Weight | How computed |
|---|---|---|---|
| C1 | **Pattern base rate** | 0.25 | `pattern.base_rate * 100`. Default 55 if unknown. |
| C2 | **Volume / RVOL confirmation** | 0.15 | 100 if RVOL ≥ 2 on trigger AND (if applicable) VDU pre-signal AND volume-divergence rule satisfied; 70 if RVOL 1.5–2; 40 if 1.2–1.5; 0 otherwise. |
| C3 | **MTF alignment** | 0.20 | `grade(P)` from §Family 11 formula × 100. |
| C4 | **Regime fit** | 0.15 | 100 if regime composite (HMM+Hurst+GEX+RV/IV) matches `pattern.regime_fit`; 50 if partial (one of three); 0 if opposite. |
| C5 | **Confluence stack** | 0.15 | +25 for each concurrent detector from a **different family** at same trigger bar (max 100). E.g., bull flag + aVWAP hold + FVG retest + pos-gamma-below = 100. |
| C6 | **R:R at trigger** | 0.10 | 100 if planned R:R ≥ 3.0; 75 if 2.0–3.0; 50 if 1.5–2.0; 0 if < 1.5. |

**Additional multiplicative penalties (applied after weighted sum):**

| Penalty | Factor | Trigger |
|---|---|---|
| Anti-pattern flag | ×0.5 | Any anti-pattern rule from `pattern.anti_pattern` fires. |
| Macro-event window | ×0.6 | Within 15 min of CPI/FOMC/NFP release. |
| Wide-spread instrument | ×0.7 | Bid/ask spread > 3× 20-bar median. |
| Freshness stale | ×0.5 | Data feed > 5 s old on trigger bar (real-time only). |

**Grade thresholds (post-penalty score):**

| Grade | Score | Advisory action | Execution action (Phase 3) |
|---|---|---|---|
| **A** | ≥ 85 | "Take the trade — full size" | Auto-submit at trigger IF: `execution_enabled=true` AND kill-switch off AND `position_size ≤ 25% risk` AND no macro-window AND instrument in whitelist |
| **B** | 70–84 | "Take at half size, manual confirm" | Advisory only — never auto-execute |
| **C** | 55–69 | "Paper-log only, watch outcome" | Advisory only |
| **D** | < 55 | "Block — anti-pattern or weak confluence" | **Auto-block** any manual entry attempt on this bar (Phase 2 dashboard pill) |

Phase 3 flip requires Kenny sign-off + ≥ 30 trading days of shadow log where realized A-grade win rate ≥ 65% AND avg R ≥ 1.5.

---

## 6. Shadow Log Schema

Append one JSON row per detected pattern to `data/pattern_grader_log.jsonl`:

```json
{
  "ts_utc": "2026-08-22T14:32:15Z",
  "instrument": "MES",
  "timeframe": "5m",
  "bar_id": "2026-08-22T14:30Z",
  "pattern_id": "bull_flag_5m",
  "family": "classical_continuation",
  "trigger_price": 5432.75,
  "stop": 5428.50,
  "target_t1": 5442.25,
  "target_t2": 5451.75,
  "planned_r_multiple": 2.24,
  "components": {
    "base_rate": 68,
    "volume": 100,
    "mtf_alignment": 82,
    "regime_fit": 100,
    "confluence": 75,
    "rr": 75
  },
  "confluence_detectors": ["bull_flag_5m","avwap_trend_hold","fvg_bisi","pos_gamma_below_flip"],
  "raw_score": 82.4,
  "penalties": {"anti_pattern": 1.0, "macro_window": 1.0, "spread": 1.0, "freshness": 1.0},
  "final_score": 82.4,
  "grade": "B",
  "regime_snapshot": {"hmm_state": "trend", "hurst": 0.58, "rv_iv": 1.05, "gex_sign": "neg"},
  "outcome_5m": null,
  "outcome_15m": null,
  "outcome_60m": null,
  "outcome_eod": null,
  "outcome_resolved_ts": null
}
```

Outcome fields filled by `scripts/pattern_grader_outcome_resolver.py` (Phase 2) at 5m/15m/60m/EOD marks: `{"realized_r": 1.42, "hit_t1": true, "hit_t2": false, "stopped": false, "expired": false}`.

---

## 7. Dashboard Integration

**Panel `pattern_grades` — add to `scripts/generate_dashboard.py`:**

```python
REPORTS["pattern_grades"] = {
    "path": REPORT_DIR / "pattern-grader-grades.json",
    "title": "Pattern Grader — Live Setups",
    "render": render_pattern_grades_panel,
    "priority": 3,
}
```

**Panel layout (HTML render):**

1. **Grade Heatmap** — instrument × timeframe grid, cell colored by top grade active (A green, B yellow, C grey, D red). Click cell → drill to setup detail.
2. **Active A-Grade Setups Table** — one row per open A-grade signal: instrument, TF, pattern_id, trigger, stop, T1, T2, R:R, age, live P&L if entered.
3. **Grade Distribution (rolling 30d)** — histogram + realized win rate per grade bucket. Sanity check that A-grades earn ≥ 65% and D-grades earn ≤ 40%.
4. **Confluence Stack Explorer** — for the top 5 active signals, expand which detectors from which families combined.
5. **Regime Trust Map** — current regime state + which pattern families are currently high-trust vs muted.
6. **Recent Blocked D-Grades (Phase 2)** — table of setups auto-blocked with anti-pattern rationale.

---

## 8. Scheduler Wiring

Add three tasks (Windows Task Scheduler):

| Task name | Script | Cadence | Purpose |
|---|---|---|---|
| `PatternGrader-Scanner-Intraday` | `scripts/pattern_grader_scanner.py --tf 1m,5m,15m` | Every 1 min, 09:25–16:15 ET | Real-time pattern detection + shadow log |
| `PatternGrader-Scanner-Swing` | `scripts/pattern_grader_scanner.py --tf 1h,4h,D` | Every 15 min, 09:30–16:00 ET | Higher-TF setups |
| `PatternGrader-Aggregator` | `scripts/pattern_grader_report.py` | Daily 16:30 ET | Roll JSONL into report + compute rolling grade quality |
| `PatternGrader-OutcomeResolver` | `scripts/pattern_grader_outcome_resolver.py` | Daily 16:35 ET (Phase 2) | Fill outcome fields for prior day's grades |

Register via `scripts/register_pattern_grader_tasks.ps1` (Codex creates).

---

## 9. Signal Registry Entries

Append to `research/signal_registry.json`:

```json
{
  "id": "pattern_grader_shadow",
  "script": "scripts/pattern_grader_scanner.py",
  "role": "shadow_grader",
  "can_submit_orders": false,
  "can_read_order_history": false,
  "execution_enabled": false,
  "owner": "pattern_grader",
  "promotion_gate": "30d shadow with A-grade win rate ≥ 0.65 AND avg realized R ≥ 1.5"
}
```

Do **NOT** add `pattern_grader_grade_a_execute` in Phase 1. That entry gets added in Phase 3 with:
- `can_submit_orders: true`
- `execution_enabled: false` (still gated by dashboard toggle + Kenny approval)
- Added to `execution_gate_audit.py` `known_order_capable_scripts` whitelist

---

## 10. Tests (must all pass before dashboard deploy)

| Test file | Coverage |
|---|---|
| `agent/tests/test_pattern_taxonomy_schema.py` | JSON schema valid; every family has ≥ 1 entry; every entry has required fields |
| `agent/tests/test_market_structure.py` | Swing detection (fractal + ATR), BOS, CHoCH, displacement, sweep — hand-crafted OHLCV fixtures |
| `agent/tests/test_pattern_detectors_classical.py` | H&S, DT/DB, triangles, flags, wedge, cup&handle — synthetic + real fixtures (SPY 2023 known cases) |
| `agent/tests/test_pattern_detectors_candlestick.py` | Context gates enforced; naked candles rejected |
| `agent/tests/test_volume_profile.py` | POC/VAH/VAL correctness against known session |
| `agent/tests/test_anchored_vwap.py` | aVWAP + σ bands against manual calc |
| `agent/tests/test_pattern_detectors_smc.py` | OB, FVG, breaker, OTE (extends existing SMC tests) |
| `agent/tests/test_pattern_detectors_wyckoff.py` | Spring + UTAD detection with hand-crafted phases |
| `agent/tests/test_pattern_detectors_orderflow.py` | Delta divergence, climax, RVOL breakout from OHLCV |
| `agent/tests/test_pattern_detectors_options.py` | GEX flip, gamma pin — mock chain data |
| `agent/tests/test_regime_composite.py` | HMM+Hurst+RV/IV+GEX composite state transitions |
| `agent/tests/test_pattern_grade_scorer.py` | Rubric weights + penalty math; A/B/C/D thresholds |
| `agent/tests/test_pattern_grader_scanner.py` | End-to-end: OHLCV → detection → grade → JSONL row |
| `agent/tests/test_pattern_grader_report.py` | Aggregator produces valid JSON schema |
| `agent/tests/test_generate_dashboard_pattern_panel.py` | Dashboard renders panel from fixture report |
| `agent/tests/test_execution_gate_audit_pattern_grader.py` | Ensure audit still passes with new scanner registered |

**Determinism gate:** All detectors must be deterministic given fixed OHLCV input — no random state, no wall-clock reads inside detector logic. Add `test_pattern_grader_replay_determinism.py` that runs scanner twice on same fixture and diff-checks JSONL output.

---

## 11. Non-Negotiables (frozen)

1. **No live execution in Phase 1 or 2.** All Phase 1/2 registry entries have `can_submit_orders=false`. Phase 3 requires Kenny approval + ≥ 30d shadow evidence.
2. **`execution_gate_audit.py` must pass** after every registry change. If it fails, revert the registry change.
3. **Never edit `agent/strategies/flip_bot.py` or `iwm_options_bot.py`** as part of this work. Pattern Grader publishes advisory; existing bots may consume grades later via `agent/src/policies/*.py` files (new, additive).
4. **Signal registry schema (`can_submit_orders`, `execution_enabled`, `can_read_order_history`) is frozen safety contract.** Do not add new required fields.
5. **Kill switch must dominate.** If `data/kill_switch.flag` present, grader still logs but dashboard suppresses A-grade actionable prompts.
6. **Data freshness.** Any grader run against real-time feed must reject bars where `now - bar_close_ts > 60s`. Log a `freshness_violation` event to the ledger.
7. **No new external API keys embedded in code.** GEX/options data reuses existing Databento + Polygon flow. If a new provider is needed, add to `.env.example` and document in handoff.
8. **Windows Task Scheduler jobs must be idempotent.** Re-registering must not create duplicates.
9. **Order-flow proxies (Phase 1) must be labeled `_proxy` in pattern IDs** (e.g., `delta_divergence_proxy`) to prevent confusion with true tick-based signals later.
10. **Backwards-compat:** existing dashboard panels must continue to render even if `pattern-grader-grades.json` is missing (guard with `if REPORT_DIR / ... exists`).

---

## 12. Phased Execution Order for Codex

**Phase 1 (this handoff — start immediately):**
1. Write `research/pattern_taxonomy.json` populated from §3 (start with top-15 setups from research pack for MVP).
2. Extend `agent/src/tools/pattern_tool.py` → add `market_structure.py` primitives (swings w/ ATR filter, BOS/CHoCH w/ displacement, sweep detection).
3. Build detector modules in `agent/src/tools/pattern_detectors/` — one file per family. Start w/ top-5 from research ranking: `orb.py`, `avwap.py`, `flag.py`, `volume_profile.py`, `inverse_hs.py`.
4. Build `regime_composite.py` (HMM state via `hmmlearn` or reuse `hmm_regime_scanner.py`; Hurst from statsmodels; RV/IV ratio from Alpaca IV feed; GEX sign from options chain).
5. Build `pattern_grade_scorer.py` implementing §5 rubric.
6. Wire `scripts/pattern_grader_scanner.py` — driver loop: for each instrument×TF, run detectors → scorer → append to JSONL.
7. Write `scripts/pattern_grader_report.py` aggregator.
8. Add dashboard panel per §7.
9. Add signal registry entry per §9.
10. Write tests per §10.
11. Run `execution_gate_audit.py`. Must pass.
12. Register scheduler tasks.
13. Deploy, generate dashboard, hand back to Kenny for verification.

**Halt after Phase 1.** Report back with:
- Count of detected patterns in first 24h shadow run
- Grade distribution histogram
- Any test failures
- Regime composite state trace

**Phase 2 (after Kenny green-light):**
1. `pattern_grader_outcome_resolver.py` (fills outcome_5m/15m/60m/EOD fields).
2. `pattern_grader_scorecard.py` (rolling grade quality: realized R by grade bucket).
3. Add remaining detector families (Wyckoff, order-flow proxies, options-flow, MTF combos).
4. Add "auto-block D-grade" advisory pill to dashboard.
5. Backtest full detector suite over ≥ 500 signals per instrument to calibrate `pattern.base_rate` empirically (override Bulkowski defaults with in-sample stats).

**Phase 3 (Kenny approval required — DO NOT AUTO-INITIATE):**
1. Ingest tick data (Databento or Rithmic decision) for true footprint / stacked-imbalance / absorption detectors.
2. Build `agent/src/policies/pattern_grade_execution_policy.py` — reads grades JSON, submits orders **only** if all §5 A-grade auto-execute preconditions met.
3. Add registry entry with `can_submit_orders=true, execution_enabled=false` initially; toggle `execution_enabled` only after Kenny confirms.
4. Update `execution_gate_audit.py` whitelist.
5. Deploy to paper account first; log 30 days; then live.

---

## 13. Success Criteria

Phase 1 complete when:
- All 16 test files pass (`pytest agent/tests/test_pattern_*.py -v`)
- `execution_gate_audit.py` passes
- Dashboard renders `pattern_grades` panel with live data after 1 hour of scanner running
- Shadow log has ≥ 20 rows across 3+ instruments and 2+ timeframes
- Regime composite emits at least one full state transition (verified in log)
- Grade distribution across 20+ signals is not all one grade (i.e., scorer discriminates)

Phase 3 promotion gate:
- ≥ 30 trading days shadow log
- A-grade realized win rate ≥ 65% AND avg realized R ≥ 1.5
- Kenny sign-off on `research/PATTERN_GRADER_PROMOTION_APPROVAL_YYYY-MM-DD.md`
- `execution_gate_audit.py` updated + passes
- Paper-account run ≥ 5 days with zero unexpected submissions

---

## Appendix A — Detection Rule Pack: Classical + Candle + Volume + Session

*(Codex: copy this section into `research/pattern_detection_rules_classical.md` verbatim.)*

**[Full content of the classical/candle/volume/session research pack from Claude session 2026-08-22 — includes exact geometric detection rules, entry/stop/target math, Bulkowski base rates, and 2026 regime notes for: H&S, IHS, DT/DB, TT/TB, triangles (asc/desc/sym), wedges, bull/bear flag, pennant, cup&handle, rounded bottom, rectangle, engulfing, hammer, hanging man, shooting star, morning/evening star, three soldiers/crows, piercing/dark cloud, tweezer, marubozu, doji types, harami, volume profile (POC/VAH/VAL/HVN/LVN), aVWAP mean-revert + trend-hold, CVD divergence, RVOL breakout, VDU pre-breakout, climax volume reversal, ORB (5/15/30/60m), IB extension/failure, midday drift, MOC imbalance, gap-and-go, gap-fade. Also anti-pattern table + MTF alignment rule + 2026 practitioner notes.]*

## Appendix B — Detection Rule Pack: SMC / ICT / Wyckoff / Order Flow / Options

*(Codex: copy this section into `research/pattern_detection_rules_smc_wyckoff.md` verbatim.)*

**[Full content of the SMC/Wyckoff/order-flow/options research pack from Claude session 2026-08-22 — includes: swing definitions (fractal + ATR), BOS/CHoCH/displacement/sweep algorithms, ICT arrays (OB/breaker/mitigation/FVG BISI+SIBI/OTE/inducement/premium-discount), kill zones, silver bullet windows, Wyckoff accumulation A-E + distribution A-E state machines w/ spring/UTAD/SOS/LPS, order-flow (stacked imbalance/absorption/delta divergence/climax/iceberg/sweep/DOM spoof) w/ tick-data requirements, options-flow (GEX flip, pos gamma pin, neg gamma trend, 0DTE pin risk, UOA, IV crush, P/C extreme), session overlay (London sweep → NY reverse), regime detector composite (HMM, Hurst, RV/IV, VIX term structure, TRIN, breadth thrust, dealer positioning), universal anti-pattern checklist, 2026 practitioner signal.]*

## Appendix C — Test Fixture Requirements

Provide the following synthetic + real OHLCV fixtures in `agent/tests/fixtures/pattern_grader/`:

- `bull_flag_spy_2023_08_15.csv` — clean bull flag, known outcome
- `head_shoulders_top_qqq_2022_01.csv` — H&S top w/ neckline break
- `inverse_hs_iwm_2023_06.csv` — inverse H&S
- `orb_5m_es_2024_02_14.csv` — 5m ORB day with clean break
- `avwap_hod_iwm_2024_03.csv` — anchored VWAP hold intraday
- `volume_profile_mes_2024_05.csv` — session w/ clear POC + VA
- `smc_bullish_ob_spy_2024_04.csv` — bullish OB + FVG + BOS sequence
- `wyckoff_spring_iwm_2023_10.csv` — accumulation spring
- `synth_random_walk.csv` — negative control (no patterns should fire above C grade)

Each fixture: OHLCV + expected pattern IDs + expected grade range (as JSON sidecar).

---

## Appendix D — Codex Cost Guardrails

- Estimated build time: 3–5 days of Codex work for Phase 1.
- Budget: pause after Phase 1 for Kenny review before Phase 2.
- Token efficiency: reuse detector patterns across timeframes (parameterize, don't duplicate).
- Testing: pytest fixtures preferred over live-feed integration tests to keep CI cheap.

---

**END OF HANDOFF. Codex: begin with §12 Phase 1 step 1 (write `pattern_taxonomy.json`). Report progress + halt after step 13.**
