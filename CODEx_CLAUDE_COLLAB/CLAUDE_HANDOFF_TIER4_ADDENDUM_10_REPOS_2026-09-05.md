# CLAUDE HANDOFF — Tier 4 Addendum (10 Workstreams)

**Date:** 2026-09-05
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Prior:**
- `CLAUDE_HANDOFF_EDGE_STACK_15_REPOS_2026-09-05.md` (Tier 1-3, 15 repos)
- `CLAUDE_HANDOFF_CV_BOOTSTRAP_STATISTICAL_GATE_2026-09-05.md` (WS-CV + WS-BOOTSTRAP)
- WS-EDGAR + WS-TRACE already shipped

**Scope:** 10 additional OSS integrations covering gaps in TCA, property-based testing, portfolio Greeks, financial NLP, chaos engineering, event risk, online learning, pattern discovery, event bus, and Kelly sizing.

---

## Session Summary

Master 15-repo handoff and CV+BOOTSTRAP handoff both dispatched. Reflection on remaining blind spots surfaced 10 additional categories not yet covered. This addendum sequences them into three sub-tiers by leverage on profitability path. The top three (WS-TCA, WS-HYPOTHESIS, WS-GREEKS) unblock claims about execution quality and prevent portfolio-level blow-ups the current per-trade sizing cannot see.

---

## Non-Negotiable Invariants (all workstreams)

- Shadow-only until 10+ reconciled outcomes AND passes WS-CV statistical gate AND human review.
- Fail-honest: missing data → status="missing", never fabricate.
- All new signals register in `agent/signal_registry.json` with WS-CV `promotion_gate` schema (min_deflated_sharpe, max_pbo, min_psr, family_key).
- No secret in source. All external API keys via `agent/.env` with rotation on any exposure.
- Budget caps env-gated per external API. Ledger every paid call.
- No auto-modification of existing bot logic; every gate/hook is opt-in via config.
- No execution wiring changes.
- Must not depend on any of the 157 pre-instrumentation alerts having full trace fields.

---

## Execution Order

**Tier 4a — ship before Tier-2 execution starts (unblocks claims):**
1. **WS-TCA** — Transaction Cost Analysis framework
2. **WS-HYPOTHESIS** — Property-based tests for order state machine
3. **WS-GREEKS** — Portfolio-level Greeks aggregator + tail hedge triggers

**Tier 4b — ship after Tier 2 lands (pairs with existing work):**
4. **WS-FINBERT** — Financial NLP over EDGAR filings + earnings calls
5. **WS-CALENDAR** — Event-scheduled risk (FOMC, earnings, ex-div, index rebals)
6. **WS-CHAOS** — Chaos engineering harness for broker/network failures
7. **WS-RIVER** — Online learning for regime drift

**Tier 4c — evaluate after Tier 4a/b prove ROI:**
8. **WS-STUMPY** — Matrix profile recurring pattern discovery
9. **WS-EVENTBUS** — NATS/Redpanda event bus + tick replay engine
10. **WS-KELLY** — Fractional Kelly sizing across correlated strategies

---

## WS-TCA — Transaction Cost Analysis Framework

**Repos:**
- https://github.com/quantopian/empyrical (metrics)
- https://github.com/stefan-jansen/pyfolio-reloaded (tear sheets)
- Custom slippage capture (in-repo)

**Dep:** `pip install empyrical-reloaded pyfolio-reloaded`

**Goal:** Measure OUR fill quality vs arrival price, mid, VWAP on every trade. Unblocks any "better fills" claim (WS-TASTY specifically).

**Files to create:**
- `agent/analytics/tca.py`
  - `class TCARecorder`
    - Captures at order submit: arrival_bid, arrival_ask, arrival_mid, arrival_ts.
    - Captures at fill: fill_price, fill_ts, venue.
    - Persists row per fill to `data/tca/fills.jsonl` (append-only, restricted perms).
  - `class TCAAnalyzer`
    - `slippage_vs_arrival_bps(fill_row) -> float`
    - `slippage_vs_mid_bps(fill_row) -> float`
    - `slippage_vs_vwap_bps(fill_row, window_bars=5) -> float`
    - Aggregations by broker, by strategy, by side, by tod bucket.
  - Refuses to compute aggregations when n<20 for a slice; returns "insufficient_data".
- `agent/tests/test_tca.py`
- `scripts/tca_report.py` — daily rollup markdown to `data/tca/reports/<date>.md`
- `docs/TCA.md`

**Files to modify:**
- `agent/iwm_options_bot.py` — pre-order hook calls `TCARecorder.snapshot_arrival(order_id, quote_snapshot)`; post-fill hook calls `TCARecorder.record_fill(order_id, fill_event)`.
- Any other order-emitting bot — same hooks.
- `scripts/generate_dashboard.py` — new **TCA** panel: rolling 30-day slippage vs mid per broker, per strategy, with WS-BOOTSTRAP CI.

**Invariants:**
- Arrival snapshot must precede broker submit by ≤1 bar; otherwise mark row `arrival_stale=true` and exclude from aggregations.
- No fabricated arrival prices. If NBBO/quote unavailable at submit → row omitted from aggregations, logged separately.
- Every TCA row carries `trace_id` from WS-TRACE for cross-reference.
- Aggregations require n>=20 else return insufficient_data.

**Tests (min):**
- `test_tca_captures_arrival_before_submit`
- `test_stale_arrival_excluded_from_aggregation`
- `test_missing_quote_omits_row_no_fabrication`
- `test_slippage_math_signs` — buy above mid = positive slippage; sell below mid = positive slippage.
- `test_insufficient_data_returned_below_n20`
- `test_trace_id_propagates_to_tca_row`

**Verification:**
```powershell
python -m pytest agent/tests/test_tca.py -q
python scripts/tca_report.py --dry-run
```

**Success gate:** After 30 fills, TCA panel shows slippage vs mid distribution w/ CI. Broker comparison possible once WS-TASTY ships.

---

## WS-HYPOTHESIS — Property-Based Tests for Order State Machine

**Repo:** https://github.com/HypothesisWorks/hypothesis

**Dep:** `pip install hypothesis`

**Goal:** Generate thousands of adversarial scenarios against order state machine (partial fills, out-of-order acks, duplicate cancels, race conditions). Existing 116 example tests catch what we anticipated; hypothesis catches what we didn't.

**Files to create:**
- `agent/tests/property/test_order_lifecycle_properties.py`
  - Strategies: order state sequences, timing jitter, duplicate events, out-of-order fills.
  - Invariants asserted:
    - Order never transitions from `filled` back to `pending`.
    - Sum of partial fills never exceeds submitted qty.
    - Cancel after fill is idempotent (no negative position).
    - Duplicate ack does not double-count fill.
    - Trace_id propagates through every state transition.
- `agent/tests/property/test_risk_gate_properties.py`
  - Strategies: random drawdown series, order sizes, budget states.
  - Invariants:
    - CDaR budget of 0 → 100% of orders rejected.
    - Increasing drawdown → monotonically non-increasing multiplier.
    - Portfolio override always wins vs per-strategy.
- `agent/tests/property/test_statistical_gate_properties.py`
  - Strategies: synthetic outcome series, trial counts.
  - Invariants:
    - DSR monotonically non-increasing in n_trials for fixed Sharpe.
    - Gate never returns `approved` for n<min_outcomes.
    - `not_ready` and `approved` are mutually exclusive; no third state confusion.
- `docs/PROPERTY_BASED_TESTING.md`

**Files to modify:**
- `pytest.ini` or equivalent — add `hypothesis` profile with `deadline=None`, `max_examples=500` for CI, `max_examples=50` for pre-commit hook.
- Pre-commit hook — run property tests at reduced example count for fast feedback.

**Invariants:**
- Property tests are additive; never replace existing example tests.
- Any counter-example found is committed to `agent/tests/regression/` as an explicit example test so it survives even if hypothesis strategy changes.
- Failure counter-examples printed with minimized shrink and full seed for reproduction.

**Tests are themselves the deliverable.** Success = counter-examples found + fixed.

**Verification:**
```powershell
python -m pytest agent/tests/property/ -q --hypothesis-show-statistics
```

**Success gate:** ≥3 real bugs found and fixed OR clean run of 500 examples per property. Publish first counter-examples in `docs/PROPERTY_BASED_TESTING.md`.

---

## WS-GREEKS — Portfolio-Level Greeks Aggregator + Tail Hedge Triggers

**Repos:**
- https://github.com/vollib/py_vollib (Black-Scholes, IV, Greeks)
- https://github.com/cvxpy/cvxpy (optimization for hedge sizing)

**Dep:** `pip install py_vollib cvxpy`

**Goal:** Aggregate delta/gamma/vega/theta across all open options positions. Trigger warning + hedge suggestion when portfolio-level Greek exceeds threshold. Prevents concurrent IWM spreads compounding into blow-up territory unseen by per-trade sizing.

**Files to create:**
- `agent/greeks/portfolio_greeks.py`
  - `def compute_portfolio_greeks(positions, spot_prices, iv_surface, rate) -> dict`
  - Uses py_vollib for per-leg Greeks; sums signed by position direction.
  - Returns `{delta, gamma, vega, theta, per_ticker_delta, per_ticker_gamma}`.
- `agent/greeks/hedge_suggester.py`
  - `def suggest_hedge(current_greeks, target_greeks, universe) -> HedgeSuggestion`
  - cvxpy LP to minimize cost of reaching neutral (or target) exposure.
  - Suggests underlying shares or vanilla options; never routed automatically.
- `agent/tests/test_portfolio_greeks.py`
- `agent/tests/test_hedge_suggester.py`
- `config/greeks_thresholds.json` — per-Greek warning + halt bands per portfolio size
- `docs/PORTFOLIO_GREEKS.md`

**Files to modify:**
- `agent/safety_gates/` — new gate `portfolio_greek_gate.py`: pre-order check that adding this trade does not breach halt band for any Greek. Fail-closed.
- `scripts/execution_gate_audit.py` — new check: portfolio_greek_gate reachable and returning decisions.
- `scripts/generate_dashboard.py` — new **Portfolio Greeks** panel:
  - Current delta/gamma/vega/theta with warning/halt band visualization.
  - Per-ticker delta breakdown.
  - Hedge suggestion (advisory only).

**Invariants:**
- Greeks computed from live IV surface, not fabricated. If IV missing for any leg → position contributes with `iv_missing=true` flag and Greek contribution treated as "unknown"; portfolio Greek reported as range not point.
- Hedge suggester output is advisory. Never auto-executes. Requires human sign-off.
- Halt band breach → new orders rejected until portfolio Greek returns inside warning band.
- `py_vollib` may fail on deep-ITM / deep-OTM at expiry; wrap with fallback and mark position `greek_unstable=true`.

**Tests (min):**
- `test_greeks_sum_signed_correctly` — long call + short call = zero delta at same strike.
- `test_missing_iv_flags_position` — no IV → position marked, Greek not fabricated.
- `test_halt_band_rejects_new_order` — synthetic portfolio at halt band → order gate returns rejection.
- `test_hedge_suggester_never_auto_executes` — output object has no `submit()` method.
- `test_range_reporting_when_iv_partial` — some positions IV-known, some not → portfolio Greek is range.

**Verification:**
```powershell
python -m pytest agent/tests/test_portfolio_greeks.py agent/tests/test_hedge_suggester.py -q
python scripts/execution_gate_audit.py --print
```

**Success gate:** Panel populates with current positions. Synthetic multi-spread scenario correctly triggers halt band + hedge suggestion.

---

## WS-FINBERT — Financial NLP Over EDGAR + Earnings Calls

**Repos:**
- https://github.com/ProsusAI/finBERT (sentiment classifier)
- https://github.com/Finnhub-Stock-API/finnhub-python (free tier: earnings calendar + transcripts)

**Dep:** `pip install transformers torch finnhub-python`

**Goal:** Grade WS-EDGAR filing signals from binary "8-K exists" to sentiment-weighted confidence. Add earnings transcript sentiment as separate signal.

**Files to create:**
- `agent/nlp/finbert_classifier.py` — batched inference; cache model locally; refuse if model download fails.
- `agent/shadow_scanners/edgar_sentiment_enricher.py` — post-processes EDGAR 8-K text via FinBERT; enriches WS-EDGAR signal row with `{sentiment, confidence, tokens_processed}`.
- `agent/shadow_scanners/earnings_transcript_sentiment.py` — polls Finnhub for new transcripts; scores; emits shadow signal.
- `agent/tests/test_finbert_classifier.py`
- `agent/tests/test_edgar_sentiment_enricher.py`
- `data/nlp/model_cache/` (gitignored)
- `docs/FINANCIAL_NLP.md`

**Files to modify:**
- `agent/signal_registry.json` — `edgar_sentiment_weighted`, `earnings_transcript_sentiment` w/ WS-CV promotion gate; family_key=`catalyst_nlp`
- `agent/.env.example` — `FINNHUB_API_KEY=`, `FINBERT_MODEL_PATH=`, `FINNHUB_DAILY_CALL_CAP=200`
- Dashboard — Catalyst NLP panel: filings scored today, transcript scores, model version hash

**Invariants:**
- Model version hash in every emitted signal row. Model swap = registered as new trial in trial_ledger.
- Empty/malformed filing text → status="skipped", never scored as neutral.
- Batch inference size bounded; refuse if VRAM/RAM check fails.
- Finnhub call cap enforced pre-request; over-cap → status="missing" remainder of day.
- Transcripts often paywalled — fall back gracefully; do not fabricate.

**Tests (min):**
- `test_finbert_deterministic_scoring` — same text → same score across runs.
- `test_empty_text_returns_skipped` — no fabrication.
- `test_model_version_persisted`
- `test_finnhub_cap_enforced`

**Success gate:** 20 EDGAR 8-Ks enriched with sentiment; signal outcomes reconciled through WS-CV gate.

---

## WS-CALENDAR — Event-Scheduled Risk Halt Gates

**Repos:**
- https://github.com/rsheftel/pandas_market_calendars (market/ex-div calendars)
- Finnhub API for earnings + FOMC calendar
- https://github.com/gsingh93/fred-py (backup for FOMC dates from FRED)

**Dep:** `pip install pandas_market_calendars`

**Goal:** Halt new-position entry within N minutes of scheduled jump-risk events (FOMC, earnings, ex-div, Russell/S&P rebal). Existing positions unaffected; kill-switch level decision only.

**Files to create:**
- `agent/calendar/event_calendar.py`
  - Aggregates event feeds; caches locally with TTL.
  - `def upcoming_events(ticker, window_minutes) -> List[Event]`
  - `def is_in_event_blackout(ticker, now, blackout_config) -> bool`
- `agent/safety_gates/event_blackout_gate.py`
- `agent/tests/test_event_calendar.py`
- `config/event_blackouts.json` — per-event-type blackout window in minutes
- `docs/EVENT_BLACKOUT.md`

**Files to modify:**
- All bots — pre-order gate call to `event_blackout_gate.check(ticker, now)`.
- `scripts/execution_gate_audit.py` — event calendar reachable within 24h.
- Dashboard — **Upcoming Events** panel.

**Invariants:**
- Event calendar unreachable → gate fails CLOSED (blackout assumed) not open. Trading pauses on missing calendar.
- Blackout affects new-position entry only; existing exits and stops always execute.
- Blackout config version pinned; changes require human review.

**Tests (min):**
- `test_missing_calendar_fails_closed`
- `test_blackout_blocks_new_position` — FOMC in 25 min, config=30 → blocked.
- `test_existing_position_exits_allowed_during_blackout`
- `test_blackout_config_version_pinned`

**Success gate:** Simulated FOMC scenario correctly blocks entries starting 30 min before, allows exits throughout.

---

## WS-CHAOS — Chaos Engineering Harness

**Repo:** https://github.com/chaostoolkit/chaostoolkit

**Dep:** `pip install chaostoolkit chaostoolkit-lib`

**Goal:** Inject broker timeout, dropped tick, WS disconnect, gap open, malformed response into staging environment. Validate fail-honest invariants before real broker misbehaves.

**Files to create:**
- `agent/chaos/experiments/` — one JSON per experiment:
  - `broker_read_timeout.json`
  - `broker_500_response.json`
  - `websocket_disconnect_and_reconnect.json`
  - `market_data_stale_60s.json`
  - `alpaca_rate_limit_burst.json`
  - `discord_webhook_403.json`
- `agent/chaos/probes.py` — chaostoolkit probes that verify invariants held (signal marked missing, no fabricated data, no orders during outage).
- `agent/chaos/actions.py` — chaostoolkit actions that inject the failure into staging.
- `agent/chaos/rollback.py` — always restores clean state.
- `scripts/run_chaos_suite.ps1` — runs all experiments against staging; publishes report.
- `docs/CHAOS_ENGINEERING.md`

**Files to modify:**
- CI (if any) — nightly chaos run against staging environment.
- Dashboard — **Chaos Status** panel: last chaos run timestamp, pass/fail per experiment.

**Invariants:**
- Chaos NEVER runs against live/production broker credentials. Refuse to start if env is production.
- Every experiment has explicit rollback; run fails if rollback fails.
- Experiment results append-only to `data/chaos/results.jsonl`.
- Any invariant violation = P0 alert, block promotion to prod until fixed.

**Tests (min):**
- `test_chaos_refuses_production_env`
- `test_rollback_verified_after_experiment`
- `test_invariant_violation_alerts`

**Success gate:** All 6 experiments run against staging without invariant violation.

---

## WS-RIVER — Online Learning for Regime Drift

**Repo:** https://github.com/online-ml/river

**Dep:** `pip install river`

**Goal:** Wrap select signals with online-updating models that adapt without retrain cycles. Pairs with WS-DRIFT (evidently detects drift → river adapts).

**Files to create:**
- `agent/ml/online_learner.py`
  - Wraps a base signal with `river.linear_model` or `river.tree` classifier that updates on each reconciled outcome.
  - Persists model state to `data/online_models/<signal_id>_state.pkl`.
  - Emits `{raw_signal, online_confidence, model_updates_count, model_version}`.
- `agent/tests/test_online_learner.py`
- `docs/ONLINE_LEARNING.md`

**Files to modify:**
- `agent/signal_registry.json` — per-signal `online_learner_enabled: bool` (off by default).
- Signal emit path — if enabled, gate emission on `online_confidence >= threshold` from registry.

**Invariants:**
- Online model is opt-in per signal.
- Model file missing/corrupt → fail-open to raw signal with WARN.
- Every update logged with pre/post loss for auditability.
- Model version = hash of (base class name + n_updates + hyperparams).

**Tests (min):**
- `test_online_disabled_by_default`
- `test_missing_state_fails_open_to_raw`
- `test_update_logged_with_loss_delta`

**Success gate:** For any signal with online enabled, updated-model outcomes must beat raw-signal outcomes on Deflated Sharpe over ≥30 reconciled outcomes.

---

## WS-STUMPY — Matrix Profile Recurring Pattern Discovery

**Repo:** https://github.com/TDAmeritrade/stumpy

**Dep:** `pip install stumpy`

**Goal:** Unsupervised discovery of recurring intraday patterns (opening drive, VWAP fade, midday chop). Signal-MINING tool, not signal itself.

**Files to create:**
- `research/stumpy_pattern_scan.py` — offline batch job over historical bars; outputs top-K recurring motifs per ticker.
- `research/stumpy_discord_scan.py` — anomaly detection (opposite of motifs).
- `agent/tests/test_stumpy_scan.py`
- `docs/PATTERN_DISCOVERY.md`

**Files to modify:**
- None in production path. Outputs feed research → candidate signal proposals → registration in signal_registry → normal promotion gate.

**Invariants:**
- Discovered patterns are RESEARCH artifacts, not auto-promoted signals.
- Each discovered pattern → explicit human review before hypothesis registration in trial_ledger.
- Guards against p-hacking: every pattern discovered counts as a trial in the family.

**Tests (min):**
- `test_motif_discovery_deterministic`
- `test_pattern_registration_writes_to_trial_ledger`

**Success gate:** 5 discovered motifs registered as candidate hypotheses; enter normal shadow-scanner + WS-CV promotion pipeline.

---

## WS-EVENTBUS — Event Bus + Tick Replay Engine

**Repos:**
- https://github.com/nats-io/nats-server (lightweight event bus)
- https://github.com/redpanda-data/redpanda (Kafka-compat, heavier, higher retention)

**Choice:** Start with NATS (simpler ops, sufficient for tick replay). Migrate to Redpanda only if retention needs exceed NATS JetStream limits.

**Dep:** `pip install nats-py`

**Goal:** Every market/decision/order event flows through event bus. Historical tick captures allow REPLAY of last N sessions through current bot code path for regression testing.

**Files to create:**
- `agent/eventbus/publisher.py` — publishes market bars, decisions, orders, fills to NATS subjects.
- `agent/eventbus/subscriber.py` — bot code subscribes rather than polling.
- `agent/eventbus/replay.py` — replays historical events into a sandboxed bot instance; compares outputs to recorded outputs (regression).
- `agent/tests/test_eventbus_replay.py`
- `docker-compose.nats.yml` — NATS JetStream sidecar
- `scripts/replay_last_n_sessions.ps1`
- `docs/EVENTBUS_AND_REPLAY.md`

**Files to modify:**
- All bots — refactor to accept event stream OR polling (feature flag). Maintain both until replay proves parity.
- Dashboard — **Replay** panel: last replay timestamp, output diff summary.

**Invariants:**
- Event bus is additive infrastructure; polling loops remain until 5-day parity confirmed.
- Replay mode uses SANDBOXED bot instance with `execution_enabled=false` hard-coded, never live broker.
- Any output diff between replay and recorded = P0; investigate before deploy.
- Retention window ≥90 days for JetStream.

**Tests (min):**
- `test_publisher_never_blocks_bot` — subscriber slow → publisher does not stall market ingestion.
- `test_replay_matches_recorded_outputs` — golden replay of known session produces byte-identical decisions.
- `test_replay_refuses_live_broker`

**Success gate:** 5 consecutive sessions where replay output diff = 0. Then bot deploys can require green replay before merge.

---

## WS-KELLY — Fractional Kelly Sizing Across Correlated Strategies

**Repos:**
- https://github.com/cvxpy/cvxpy (portfolio optimization)
- Riskfolio-Lib (already Tier-1)

**Goal:** Compute fractional Kelly bet sizes accounting for correlation across concurrent strategies. Combines with Riskfolio CDaR budget.

**Files to create:**
- `agent/sizing/kelly_sizer.py`
  - `def kelly_size(strategy_id, edge, variance, correlation_matrix, kelly_fraction=0.25) -> float`
  - Fractional Kelly (default 0.25 = quarter-Kelly).
  - Correlation matrix from historical strategy returns.
  - Bounded [0, per_strategy_cap].
- `agent/tests/test_kelly_sizer.py`
- `config/kelly_config.json` — kelly_fraction, correlation lookback, min_samples_for_edge
- `docs/KELLY_SIZING.md`

**Files to modify:**
- All bots — size = min(Riskfolio_CDaR_size, Kelly_size, hard_cap). Most conservative wins.
- Dashboard — **Sizing Attribution** panel: which constraint bound the last order (CDaR / Kelly / hard cap).

**Invariants:**
- Kelly requires ≥60 outcomes for edge estimate; else Kelly_size = 0 (do not size on shaky edge).
- Full Kelly disallowed; kelly_fraction max = 0.5 enforced in code.
- Correlation matrix refresh nightly; stale correlations (>7 days) → Kelly_size falls back to 0.
- Kelly ALWAYS combined with CDaR budget via min(); never overrides safety layer.

**Tests (min):**
- `test_kelly_zero_below_min_samples`
- `test_full_kelly_disallowed`
- `test_min_of_kelly_cdar_hardcap_selected`
- `test_stale_correlation_zeros_kelly`
- `test_negative_edge_returns_zero`

**Success gate:** Backtest shows Kelly sizing improves risk-adjusted return vs flat sizing by ≥10% Sharpe over 60+ outcomes, with drawdown ≤ flat sizing.

---

## Skip / Traps (Reminder)

- **stocksera, WSB-copy bots** — untested edge, high DD.
- **auto-GPT-trading forks** — LLM-drives-broker, catastrophic fills documented.
- **darts deep-learning TS** — high hype, low yield for financial series.
- **OpenBB whole platform** — data aggregator overkill given Databento + Alpaca + EDGAR + Quiver + Finnhub already cover the surface.
- **QuantLib-SWIG** — only if exotic options enter scope; vanilla + spreads don't need it.

---

## Combined End-of-Session Verification Template

```powershell
python scripts/signal_stack_health_report.py --no-write
# → OK count higher; STALE=0; ERROR=0

python scripts/execution_gate_audit.py --print
# → passed=True; issues=0 (event_blackout + portfolio_greek gates present)

python -m pytest agent/tests/ -q
# → all pass; count = previous + new workstream tests

python -m pytest agent/tests/property/ --hypothesis-show-statistics
# → all properties hold; counter-examples committed as regressions

python scripts/generate_dashboard.py
# → New panels: TCA, Portfolio Greeks, Upcoming Events, Chaos Status, Sizing Attribution
```

---

## Open Positions / Active Risks

- No live positions.
- Prior handoffs (Tier 1-3 master + CV/BOOTSTRAP) may be in-flight. Codex: confirm prior work landed clean before starting Tier 4a. If gate audit fails post-CV, fix before Tier 4a starts (Tier 4a depends on WS-CV promotion gate schema).
- No new external API credentials introduced by Tier 4a; Tier 4b introduces Finnhub key — rotate handling follows existing envelope.

---

## Next Session Priority Action for Codex

**Start with WS-TCA** (Tier 4a #1). Fast wins:
1. Slippage capture wires into existing order path w/o logic changes.
2. Enables comparison for WS-TASTY once brokered.
3. Panel provides operator confidence in fill quality.

Then **WS-HYPOTHESIS** — property tests likely find real bugs in existing 116-test coverage. Fix each before moving on.

Then **WS-GREEKS** — closes the portfolio-level blow-up gap before Tier 2 increases position count.

Do NOT start Tier 4b until Tier 4a lands AND Tier 2 (Prefect / Tastytrade / GEX) proves parity.

---

## Known Caveats / Deferred

- **WS-HYPOTHESIS counter-examples**: may block progress temporarily. Fix each; don't skip.
- **WS-GREEKS**: `py_vollib` fallback needed for deep-ITM/OTM at expiry; do not silently return zero Greek.
- **WS-CHAOS**: never against production. Enforce env check.
- **WS-EVENTBUS**: heaviest workstream in this addendum. If NATS ops complexity exceeds team bandwidth, defer entirely — polling continues to work.
- **WS-KELLY**: Kelly on financial data is theoretically optimal but empirically fragile. Fractional (≤0.25) is mandatory. Any implementation that removes the fractional cap is a code-review failure.
- **WS-FINBERT model download**: first run pulls ~500MB. Ensure network + disk cap in staging before first invocation.

---

## Handoff Complete

Codex: acknowledge in BRIDGE, sequence per tier, ship shadow-only, gate through WS-CV statistics, never bypass safety layer. Every claim requires paired-bootstrap CI excluding zero before it enters the record.
