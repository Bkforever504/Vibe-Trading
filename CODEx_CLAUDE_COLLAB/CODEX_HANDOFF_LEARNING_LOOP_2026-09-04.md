# Codex Handoff — Exponential Learning Loop from Delivered Alerts

**Date**: 2026-09-04
**Author**: Claude (spec)
**Executor**: Codex
**Depends on**: `CODEX_HANDOFF_EXECUTION_PRECISION_2026-09-04.md` (must land first — this loop consumes its outputs)
**Mode**: shadow-only. Nomination-only tuning. No auto-mutation of live rules. No execution flag flips.

## Goal

Every delivered alert becomes training data. System proposes concrete parameter changes for timing, watcher thresholds, cooldowns, grade cutoffs, and Discord routing — reviewed by human, promoted deliberately. Improvement compounds because each session's outcomes narrow the parameter space.

## Non-negotiable invariants (inherit from prior handoffs)

1. Shadow-only. `execution_enabled=false`, `can_submit_orders=false` everywhere.
2. Every nomination file must include `automatic_parameter_changes: false` and `promotion_status: "human_review_required"`.
3. Minimum sample per bucket before any nomination: `MIN_SAMPLE = 30` post-delivery outcomes.
4. Regime-conditional buckets only. No cross-regime pooling.
5. Timestamps evaluated from Discord delivery, not signal bar.
6. `order_authority_invariant` must return `violations=0`.

---

## Workstream 6 — Alert attribution ledger

**Problem**: Chart-review shows outcome per alert but doesn't tell you WHY it won or lost. Cannot learn without attribution.

**Implement** `scripts/alert_attribution_ledger.py`:

Input sources (all from prior handoff outputs):
- `~/.vibe-trading/reports/discord-alert-chart-review.json` — per-alert post-delivery outcome
- `~/.vibe-trading/data/governed_shadow_alert_events.jsonl` — delivery timestamps
- `~/.vibe-trading/data/governed_shadow_outcomes.jsonl` — reconciled outcomes
- `~/.vibe-trading/data/daily_level_map_alert_events.jsonl`
- `~/.vibe-trading/data/spy_level_reaction_alert_events.jsonl` (from WS1)
- `~/.vibe-trading/data/bplus_spotlight_log.jsonl`

For each alert emit an attribution row keyed by `attribution_id = sha256(alert_source|event_id)`:

```json
{
  "attribution_id": "<sha>",
  "alert_source": "governed_shadow|bplus_spotlight|daily_level_map|spy_level_reaction|core_index_tape_watcher",
  "event_id": "<sha>",
  "symbol": "SPY",
  "setup": "orb_breakout",
  "grade": "B+",
  "direction": "LONG",
  "regime_bucket": {
    "vix_bucket": "15-20|20-25|25+",
    "trend_bucket": "up|chop|down",
    "session_slot": "0930-1000|1000-1100|1100-1400|1400-1600",
    "day_of_week": "MON|TUE|WED|THU|FRI"
  },
  "latency_breakdown_seconds": {
    "signal_bar_to_decision": <float>,
    "decision_to_alert": <float>,
    "alert_to_discord_delivered": <float>,
    "total_signal_to_delivered": <float>
  },
  "entry_quality": {
    "bar_completed_at": "<UTC Z>",
    "delivered_at": "<UTC Z>",
    "first_tradable_bar_at": "<UTC Z>",
    "gap_through_entry": true|false,
    "reprice_slippage_bps": <float>,
    "invalidated_before_entry": true|false
  },
  "outcome": {
    "terminal_event": "target|initial_stop|time_exit|ambiguous_excluded|invalidated_before_entry",
    "outcome_r": <float>|null,
    "minutes_to_terminal": <int>|null,
    "mfe_r": <float>,
    "mae_r": <float>
  },
  "attribution": {
    "won_because": ["fast_delivery"|"clean_entry"|"regime_match"|"repeat_confirmation"|"institutional_confluence"|null],
    "lost_because": ["late_delivery"|"gap_through"|"regime_mismatch"|"stale_setup"|"vwap_wrong_side"|"duplicate_fatigue"|null],
    "confidence": "high|medium|low"
  },
  "execution_enabled": false,
  "can_submit_orders": false
}
```

**Attribution rules** (deterministic, no LLM):
- `late_delivery`: `total_signal_to_delivered > 240` seconds AND outcome `initial_stop` within first 5 post-delivery bars.
- `gap_through`: `entry_quality.gap_through_entry=true` AND `reprice_slippage_bps > 15`.
- `regime_mismatch`: outcome `initial_stop` AND same-regime-bucket historical hit rate < 40% over prior 30 samples.
- `stale_setup`: `bar_completed_at` to `first_tradable_bar_at` > 6 minutes.
- `vwap_wrong_side`: direction LONG but delivered_at close < session VWAP (short case symmetric).
- `duplicate_fatigue`: prior 3 alerts same symbol same direction within 30 minutes.
- `won_because` mirrors the inverse plus positive triggers (`institutional_confluence` when confluence card was `confluence_observed`, `repeat_confirmation` when repeat_count >= 2).

Write to append-only ledger `~/.vibe-trading/data/alert_attribution_ledger.jsonl` and report `~/.vibe-trading/reports/alert-attribution.json`.

**Runner step**: after `discord_alert_chart_review.py`.

**Test** `agent/tests/test_alert_attribution_ledger.py`:
- Late-delivery loss → `lost_because` contains `late_delivery`.
- Fast-delivery target hit + confluence → `won_because` contains both.
- Idempotent by attribution_id.

---

## Workstream 7 — Timing-parameter nomination

**Problem**: Watcher thresholds (`REVERSAL_NEW_EXTREME_BPS`, rvol cutoffs, cooldown durations, drawdown/rebound bps) are hand-tuned. Need data-driven nomination.

**Implement** `scripts/timing_parameter_nominations.py`:

For each tunable parameter in `scripts/core_index_tape_watcher.py`:
- Read last 60 sessions of attribution ledger.
- Bucket by regime.
- For each bucket, simulate the outcome curve as parameter varies ±30% in 10% steps (offline replay against completed 1m bars — no live re-fire).
- Find the parameter value that maximizes `median outcome_r * hit_rate` on that bucket.
- If proposed value differs from current by >15% AND sample size >= 30 AND monotonic improvement across at least 3 adjacent steps, emit a nomination.

Nomination schema:
```json
{
  "nomination_id": "<sha>",
  "parameter_name": "REVERSAL_NEW_EXTREME_BPS",
  "current_value": 12.0,
  "proposed_value": 18.0,
  "regime_bucket": {...},
  "sample_size": 47,
  "evidence": {
    "current_median_r": -0.30,
    "proposed_median_r": 0.42,
    "current_hit_rate": 0.458,
    "proposed_hit_rate": 0.553,
    "monotonic_improvement_steps": 4
  },
  "action": "nominate_parameter_shift_review",
  "promotion_status": "human_review_required",
  "automatic_parameter_changes": false,
  "execution_enabled": false,
  "can_submit_orders": false
}
```

Write `~/.vibe-trading/reports/timing-parameter-nominations.json` and `~/.vibe-trading/data/timing_parameter_nominations.jsonl` (idempotent).

**Explicit forbidden**: no code path that writes back into `core_index_tape_watcher.py` constants. Human edits are the only promotion path.

**Runner step**: nightly only, after 4:15 PM ET. Not intraday.

**Test** `agent/tests/test_timing_parameter_nominations.py`:
- Synthetic 47-sample bucket with monotonic improvement across 4 steps → nomination emitted.
- 29-sample bucket → no nomination (below MIN_SAMPLE).
- Non-monotonic → no nomination.

---

## Workstream 8 — Latency budget scorecard

**Problem**: Discord transport is 5s median but signal→delivered is 400+ seconds. Where's the time going?

**Implement** `scripts/latency_budget_scorecard.py`:

For each alert in attribution ledger:
- Read `latency_breakdown_seconds`.
- Group by alert_source.
- Compute per-stage p50/p90/p99 for last 30 sessions.
- Flag any stage where p90 > `target_p90`:
  - `signal_bar_to_decision`: target 30s
  - `decision_to_alert`: target 5s
  - `alert_to_discord_delivered`: target 10s
  - `total_signal_to_delivered`: target 60s (governed 5m spine) or 15s (core index tape watcher 1m spine)

Emit report `~/.vibe-trading/reports/latency-budget-scorecard.json`:
```json
{
  "provider": "latency_budget_scorecard",
  "generated_at": "<Z>",
  "sessions_reviewed": 30,
  "by_source": {
    "governed_shadow": {
      "signal_bar_to_decision": {"p50": 12, "p90": 45, "target": 30, "status": "over_budget"},
      ...
    }
  },
  "breach_summary": [
    {"source": "governed_shadow", "stage": "signal_bar_to_decision", "p90": 45, "target": 30, "recommendation": "check cadence scheduler drift or python cold-start"}
  ],
  "execution_enabled": false,
  "can_submit_orders": false
}
```

Wire into `generate_dashboard.py` — new panel "Latency Budget" showing per-source per-stage bars with target line.

**Runner step**: after attribution ledger.

**Test** `agent/tests/test_latency_budget_scorecard.py`: synthetic breaches → correct recommendations.

---

## Workstream 9 — Regime-conditional grade nominations (extends WS2)

**Problem**: WS2 recalibrates grades globally. B+ might work in VIX 20-25 uptrend but fail in VIX 15-20 chop. Global recalibration hides that.

**Extend** `scripts/post_delivery_grade_calibrator.py` (from prior handoff):

Instead of grouping by `(setup, grade, symbol_class)`, group by `(setup, grade, symbol_class, regime_bucket)`.

Emit **regime-conditional** nominations. Each nomination proposes:
- Route this (setup, grade) to Discord in this regime.
- Route to dashboard-only in this other regime.
- Suppress entirely below this regime bucket floor.

Nomination schema adds:
```json
{
  "regime_bucket": {...},
  "current_routing": "discord",
  "proposed_routing": "dashboard_only|discord|suppressed",
  "evidence_by_regime": {...}
}
```

Human approves per regime. Existing global recalibration in WS2 stays as coarser first-pass.

**Test** `agent/tests/test_regime_conditional_grade_nominations.py`: same grade wins in one regime, loses in another → two separate nominations with opposite routing recommendations.

---

## Workstream 10 — Nomination promotion audit trail

**Problem**: Nominations accumulate. Need visibility on what was reviewed, promoted, rejected, and how outcomes changed after promotion.

**Implement** `scripts/nomination_promotion_ledger.py`:

Reads all four nomination JSONLs:
- `governed_shadow_rule_nominations.jsonl`
- `grade_recalibration_nominations.jsonl`
- `timing_parameter_nominations.jsonl`
- (WS9) `regime_conditional_grade_nominations.jsonl`

Cross-references with `docs/PROMOTIONS_APPROVED.md` (human-edited file, plain markdown checklist).

Emits report `~/.vibe-trading/reports/nomination-promotion-audit.json`:
- Total nominations by type.
- Approved / rejected / pending counts.
- Days-since-last-approval.
- Post-promotion outcome delta (7-day rolling median R before vs after promotion date).

Dashboard panel: "Learning Loop Health" — nomination pipeline throughput + post-promotion outcome trend.

**Test** `agent/tests/test_nomination_promotion_ledger.py`: synthetic approved nomination with 7 days of pre/post data → correct outcome delta.

---

## Required checks

```powershell
python -m py_compile scripts/alert_attribution_ledger.py scripts/timing_parameter_nominations.py scripts/latency_budget_scorecard.py scripts/nomination_promotion_ledger.py scripts/post_delivery_grade_calibrator.py scripts/generate_dashboard.py
python -m pytest agent/tests/ -q -k "attribution or timing_parameter or latency_budget or nomination_promotion or regime_conditional"
python scripts/order_authority_invariant.py
git diff --check
```

## Deliverable back to Claude

Report with:
- Files touched (path:line)
- Test counts
- Sample attribution row (one won, one lost, with attribution reasons)
- Sample timing-parameter nomination with monotonic evidence
- Sample latency breach recommendation
- Invariant status (must be violations=0)

## Compounding effect

Each session appends to attribution ledger. WS7 nightly job re-simulates parameter curves against enlarged sample. WS10 tracks whether promoted changes actually improved outcomes. Grade routing (WS9) narrows further per regime.

Result: parameter space collapses toward the ridge that wins in each regime. Not machine learning in the fancy sense — deterministic grid search + human review — but the search space shrinks every session, so proposed changes get sharper. That is the exponential path.
