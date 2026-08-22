from __future__ import annotations

from scripts.cisd_promotion_tracker import build_status, evaluate_gate, wilson_lower_bound


def _rows(count: int, wins: int, *, dates: int = 30, probability: float = 0.7) -> list[dict]:
    return [
        {
            "detection_id": f"cisd-{index}",
            "pattern_id": "cisd_bullish" if index % 2 else "ict_cisd_universal_model",
            "trigger_bar_ts": f"2026-07-{index % dates + 1:02d}T14:00:00Z",
            "probability": probability,
            "outcome_60m": {"realized_r": 1.0 if index < wins else -1.0, "won": index < wins},
        }
        for index in range(count)
    ]


def test_wilson_bound_and_brier_metrics_are_deterministic() -> None:
    assert round(wilson_lower_bound(60, 100), 6) == 0.502001
    status = build_status(_rows(100, 66), now_utc="2026-08-22T21:30:00Z")
    assert status["n_outcomes"] == 100
    assert status["n_unique_dates"] == 30
    assert status["win_rate_raw"] == 0.66
    assert status["wilson_lower_bound_95"] > 0.55
    assert status["brier_score"] < status["brier_baseline"]
    assert status["brier_skill"] > 0
    assert status["eligible_for_validated_promotion"] is True
    assert status["execution_enabled"] is False
    assert status["can_submit_orders"] is False


def test_gate_fails_closed_at_sample_and_exact_metric_edges() -> None:
    pending = build_status(_rows(99, 70), now_utc="2026-08-22T21:30:00Z")
    assert pending["eligible_for_validated_promotion"] is False
    assert "n_outcomes < 100" in pending["gate_reasons_pending"]

    assert evaluate_gate(n_outcomes=100, n_unique_dates=30, wilson=0.549, brier_skill=0.1)[0] is False
    assert evaluate_gate(n_outcomes=100, n_unique_dates=30, wilson=0.551, brier_skill=0.1)[0] is True
    assert evaluate_gate(n_outcomes=100, n_unique_dates=30, wilson=0.551, brier_skill=0.0)[0] is False


def test_tracker_deduplicates_latest_outcome_snapshot_and_aliases() -> None:
    rows = _rows(1, 1, dates=1)
    rows.append({**rows[0], "outcome_60m": {"realized_r": -1.0, "won": False}, "resolved_at": "2026-08-22T20:00:00Z"})
    status = build_status(rows, now_utc="2026-08-22T21:30:00Z")
    assert status["n_outcomes"] == 1
    assert status["wins"] == 0
    assert status["pattern_id"] == "ict_cisd_universal_model"
