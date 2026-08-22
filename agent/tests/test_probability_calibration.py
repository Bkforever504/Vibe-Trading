from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.probability_calibration import chronological_holdout, probability_metrics


def test_probability_metrics_reports_reliability_and_skill() -> None:
    samples = [
        {"timestamp": "2026-01-01T15:00:00Z", "probability": 0.8, "outcome": 1},
        {"timestamp": "2026-01-02T15:00:00Z", "probability": 0.7, "outcome": 1},
        {"timestamp": "2026-01-03T15:00:00Z", "probability": 0.2, "outcome": 0},
        {"timestamp": "2026-01-04T15:00:00Z", "probability": 0.3, "outcome": 0},
    ]
    result = probability_metrics(samples)
    assert result["sample_count"] == 4
    assert result["brier_skill_vs_base_rate"] > 0
    assert result["log_loss"] is not None
    assert result["expected_calibration_error"] is not None
    assert sum(row["count"] for row in result["reliability_bins"]) == 4


def test_probability_metrics_rejects_non_probabilities() -> None:
    result = probability_metrics([
        {"timestamp": "2026-01-01T15:00:00Z", "probability": 8, "outcome": 1},
        {"timestamp": "2026-01-02T15:00:00Z", "probability": 0.8, "outcome": 2},
    ])
    assert result["sample_count"] == 0


def test_chronological_holdout_never_trains_on_same_date() -> None:
    start = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
    samples = []
    for index in range(20):
        samples.append({
            "id": f"warmup-{index}",
            "timestamp": start.isoformat(),
            "probability": 0.75 if index % 2 == 0 else 0.25,
            "outcome": 1 if index % 2 == 0 else 0,
        })
    samples.append({
        "id": "first-holdout",
        "timestamp": (start + timedelta(days=1)).isoformat(),
        "probability": 0.75,
        "outcome": 1,
    })
    result = chronological_holdout(samples, minimum_training_samples=20)
    assert result["holdout_count"] == 1
    assert result["holdout_dates"] == 1
    assert result["available_input_count"] == 21


def test_chronological_holdout_stays_insufficient_below_review_gate() -> None:
    start = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
    samples = [
        {
            "id": str(index),
            "timestamp": (start + timedelta(days=index)).isoformat(),
            "probability": 0.8 if index % 2 == 0 else 0.2,
            "outcome": 1 if index % 2 == 0 else 0,
        }
        for index in range(25)
    ]
    result = chronological_holdout(samples, minimum_training_samples=10)
    assert result["holdout_count"] == 15
    assert result["status"] == "insufficient_holdout"
    assert result["authority"] == "read_only_evidence_not_execution"
