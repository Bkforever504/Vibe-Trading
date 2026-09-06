# Codex Handoff — Execution Precision Workstreams

**Date**: 2026-09-04
**Author**: Claude (audit + spec)
**Executor**: Codex
**Mode**: shadow-only. Do NOT flip execution_enabled anywhere.

## Goal

Close the five gaps that block pinpoint execution quality. User approved all five.

---

## Workstream 1 — Persist mapped-level Discord payloads (P0 audit gap)

**Problem**: 36 mapped-level state alerts delivered today without permanent event payloads. Chart-review cannot evaluate them.

**Investigate**:
- `scripts/spy_level_reaction_shadow.py` — no `_append` / `events.jsonl` writer found via grep. Confirm and add one that mirrors `governed_shadow_alert.py:145-154` shape.
- `scripts/daily_level_map_shadow.py:653` already appends to `daily_level_map_alert_events.jsonl`. Verify every Discord send path writes an event row before returning.

**Required event schema** (match existing):
```json
{
  "event_id": "<sha256 of symbol|level|state|delivery_minute>",
  "attempted_at": "<UTC ISO Z>",
  "delivered": true|false,
  "attempts": <int>,
  "error_class": null|"http_<code>"|"<exception_class>",
  "symbol": "<upper>",
  "level": "<name>",
  "state": "ARMED|CONFIRMED|INVALIDATED|OBSERVE",
  "execution_enabled": false,
  "can_submit_orders": false
}
```

**Extend** `scripts/discord_alert_chart_review.py`:
- Add `SPY_LEVEL_EVENTS = VIBE_HOME / "data" / "spy_level_reaction_alert_events.jsonl"` constant.
- Include in the sources union so mapped-level alerts get delivery-timestamp evaluation.

**Test**: append a `test_mapped_level_alerts_are_persisted_and_evaluated` case in `agent/tests/test_discord_alert_chart_review.py` (create if missing) — feed a synthetic ARMED event, assert it appears in the review report keyed by delivered_at.

---

## Workstream 2 — Grade recalibration from post-delivery outcomes

**Problem**: B+ hitting 33.3% with −1R median. Grade thresholds don't match post-delivery reality.

**Investigate**:
- `scripts/grade_probability_service.py` and `scripts/probability_calibration.py` — these already exist. Confirm they train on outcome data.
- Feed source must be `discord_alert_chart_review.py` post-delivery outcomes, not raw scanner outcomes (that's the calibration mistake).

**Implement**:
- New script `scripts/post_delivery_grade_calibrator.py`:
  - Reads `~/.vibe-trading/reports/discord-alert-chart-review.json` daily outcomes.
  - Groups by (setup, grade, symbol_class in {index, mag7, other}).
  - Requires `MIN_SAMPLE = 30` post-delivery outcomes per bucket.
  - Emits a **nomination** report: proposed threshold shifts, current vs proposed hit rate + median R.
  - **Does not auto-mutate** any grade rule. Human review required — same policy as `governed_shadow_rule_update.py:60-70`.
  - Writes `~/.vibe-trading/reports/grade-recalibration-nominations.json` and appends `~/.vibe-trading/data/grade_recalibration_nominations.jsonl` (idempotent by nomination_id hash).

**Wire into runner**: add step after `governed_shadow_rule_update` in `scripts/run_intraday_opportunity_radar.ps1`.

**Test**: `agent/tests/test_post_delivery_grade_calibrator.py` — synthetic 30 B+ outcomes with 33% wins → nomination action `nominate_grade_tightening_review`, `automatic_parameter_changes: false`.

---

## Workstream 3 — Premarket thesis + NBBO options-flow layer

**Problem**: Cannot detect pre-open puts (competitor's 9:30 SPY case). Need premarket bias + NBBO flow.

**Existing infra to reuse**:
- `scripts/premarket_opportunity_radar.py` — already runs premarket.
- `scripts/fetch_databento_options_nbbo.py` — NBBO fetch exists.

**Implement**:
- New script `scripts/premarket_thesis_shadow.py`:
  - Runs 8:00–9:25 ET.
  - Inputs: premarket radar top candidates, Databento NBBO snapshot for SPY/QQQ/IWM 0DTE + weekly puts/calls.
  - Detects: unusual premium prints (>$50k), skew, put/call flow ratio anomaly, gap-and-hold vs gap-and-fade setups.
  - Emits shadow thesis card with `direction`, `conviction`, `evidence`, `expires_at` (10:00 ET default).
  - Independent critic card in `governed_shadow_decision.evidence_cards` — mirror the institutional_confluence_shadow pattern.
  - **Fail-honest**: if NBBO feed unavailable, emit `status: "missing"`, don't fabricate from OHLCV.
- Register scheduled task: 8:00 ET single trigger.

**Alert routing**: premarket theses go to Discord as OBSERVE-only with `[PREMARKET THESIS]` prefix. No SIMULATE/ARMED — those wait for the tape watcher + governed spine after open.

**Test**: `agent/tests/test_premarket_thesis_shadow.py` — synthetic NBBO with unusual put flow → thesis direction SHORT, conviction "high". Missing NBBO → status missing, no fabrication.

---

## Workstream 4 — Live-execution readiness draft (do NOT enable)

**Problem**: No formal go/no-go criteria for eventual promotion from shadow to live.

**Implement**:
- New doc `docs/LIVE_EXECUTION_PROMOTION_CRITERIA.md`:
  - Minimum 30 sessions of clean shadow data with delivery-timestamp evaluation.
  - Grade recalibration nominations reviewed + accepted by human.
  - Chart-review win rate ≥55% at target grade, median R ≥+0.5.
  - Zero order_authority violations for 30 consecutive days.
  - Discord delivery latency <10s median for 30 days.
  - Kill-switch tested end-to-end (manual drill).
  - Sizing: max 1% account risk per trade at promotion; halves after any 3-loss day.
- New script `scripts/execution_readiness_scorecard.py`:
  - Reads all shadow reports, computes each criterion daily.
  - Emits `~/.vibe-trading/reports/execution-readiness.json`: per-criterion PASS/FAIL/PENDING + days remaining.
  - **Cannot flip any config flag**. Reports only. Human promotion is a separate manual step.
- Dashboard section in `generate_dashboard.py`: render readiness scorecard as a progress panel.

**Invariant checks in the doc**:
- Live execution requires explicit CLAUDE.md edit setting `execution_enabled: true` on a specific strategy AND passing all criteria.
- Any promotion PR must include the readiness report snapshot as evidence.

**Test**: `agent/tests/test_execution_readiness_scorecard.py` — synthetic 30-day pass → all PASS; synthetic 29-day pass → SESSIONS PENDING; violation on day 15 → resets counter.

---

## Workstream 5 — Delivery-timestamp evaluation everywhere

**Problem**: Some paths still evaluate from signal-bar timestamp instead of Discord delivery timestamp.

**Grep and fix**:
```
rg -n "bar_completed_at" scripts/ | grep -Ev "governed_shadow_(decision|outcome|lifecycle)"
```
Every match that scores/reviews an alert must switch to `delivered_at` (or `first_complete_bar_after_delivery`). Governed decision/lifecycle/outcome are correct as-is because they use bar_completed_at for candidate identity, not for evaluation timing.

**Specifically audit**:
- `scripts/aplus_spotlight.py`
- `scripts/simple_price_action_alerts.py`
- `scripts/continuous_improvement_scorecard.py`
- `scripts/outcome_science_report.py`

**Add invariant test**: `agent/tests/test_delivery_timestamp_invariant.py` — verify each of the above scripts, when given an alert with `delivered_at` 3 minutes after `bar_completed_at`, uses the later timestamp for outcome bar filtering.

---

## Required checks (before returning)

```powershell
python -m py_compile scripts/spy_level_reaction_shadow.py scripts/daily_level_map_shadow.py scripts/discord_alert_chart_review.py scripts/post_delivery_grade_calibrator.py scripts/premarket_thesis_shadow.py scripts/execution_readiness_scorecard.py scripts/generate_dashboard.py
python -m pytest agent/tests/ -q -k "chart_review or grade or premarket_thesis or execution_readiness or delivery_timestamp or mapped_level"
python scripts/order_authority_invariant.py
git diff --check
```

**Non-negotiable**: order_authority_invariant must return `violations=0`. No new `execution_enabled=true` or `can_submit_orders=true` anywhere.

## Deliverable back to Claude

Short report with:
- Files touched (path:line)
- Test counts (passed/failed)
- Any invariant deviation (should be none)
- Sample recalibration nomination + sample premarket thesis card (redacted if needed)

If a workstream requires credentials Codex doesn't have (Databento key for NBBO), stub the adapter with a `status: "not_configured"` return path and flag it in the report. Do not fabricate.
