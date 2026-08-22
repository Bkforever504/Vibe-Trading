"""Point-in-time probability calibration helpers for read-only bot evidence.

The helpers deliberately accept only frozen probabilities and resolved binary
outcomes. Setup/ranking scores must not be converted to probabilities here.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable


EPSILON = 1e-6


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip_probability(value: float) -> float:
    return min(1.0 - EPSILON, max(EPSILON, value))


def _normalized(samples: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        probability = _finite(sample.get("probability"))
        outcome = _finite(sample.get("outcome"))
        timestamp = _timestamp(sample.get("timestamp"))
        if probability is None or not 0.0 <= probability <= 1.0 or outcome not in {0.0, 1.0}:
            continue
        rows.append(
            {
                **sample,
                "probability": _clip_probability(probability),
                "outcome": int(outcome),
                "_timestamp": timestamp,
            }
        )
    return rows


def probability_metrics(samples: Iterable[dict[str, Any]], *, bin_count: int = 5) -> dict[str, Any]:
    rows = _normalized(samples)
    if not rows:
        return {
            "sample_count": 0,
            "status": "insufficient_n",
            "brier_score": None,
            "base_rate_brier_score": None,
            "brier_skill_vs_base_rate": None,
            "log_loss": None,
            "expected_calibration_error": None,
            "calibration_gap": None,
            "reliability_bins": [],
        }
    probabilities = [float(row["probability"]) for row in rows]
    outcomes = [int(row["outcome"]) for row in rows]
    observed_rate = sum(outcomes) / len(outcomes)
    mean_probability = sum(probabilities) / len(probabilities)
    brier = sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes)) / len(rows)
    base_brier = sum((observed_rate - outcome) ** 2 for outcome in outcomes) / len(rows)
    skill = None if base_brier == 0 else 1.0 - brier / base_brier
    log_loss = -sum(
        outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability)
        for probability, outcome in zip(probabilities, outcomes)
    ) / len(rows)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(max(1, bin_count)):
        lower = index / max(1, bin_count)
        upper = (index + 1) / max(1, bin_count)
        members = [
            row for row in rows
            if lower <= float(row["probability"]) < upper
            or (index == bin_count - 1 and lower <= float(row["probability"]) <= upper)
        ]
        if not members:
            continue
        predicted = sum(float(row["probability"]) for row in members) / len(members)
        observed = sum(int(row["outcome"]) for row in members) / len(members)
        gap = predicted - observed
        ece += len(members) / len(rows) * abs(gap)
        bins.append(
            {
                "lower": round(lower, 4),
                "upper": round(upper, 4),
                "count": len(members),
                "mean_probability": round(predicted, 4),
                "observed_rate": round(observed, 4),
                "gap": round(gap, 4),
            }
        )
    distinct_dates = {
        row["_timestamp"].date().isoformat()
        for row in rows
        if isinstance(row.get("_timestamp"), datetime)
    }
    unique_probabilities = len({round(value, 6) for value in probabilities})
    return {
        "sample_count": len(rows),
        "distinct_dates": len(distinct_dates),
        "status": "ok" if len(rows) >= 30 and len(distinct_dates) >= 20 else "insufficient_n",
        "mean_probability": round(mean_probability, 6),
        "observed_rate": round(observed_rate, 6),
        "calibration_gap": round(mean_probability - observed_rate, 6),
        "unique_probability_count": unique_probabilities,
        "discrimination_status": "unmeasurable_saturated_probability" if unique_probabilities < 2 else "measurable",
        "brier_score": round(brier, 6),
        "base_rate_brier_score": round(base_brier, 6),
        "brier_skill_vs_base_rate": round(skill, 6) if skill is not None else None,
        "log_loss": round(log_loss, 6),
        "expected_calibration_error": round(ece, 6),
        "reliability_bins": bins,
    }


def _fit_platt(rows: list[dict[str, Any]], *, regularization: float = 1.0) -> tuple[float, float] | None:
    if len(rows) < 2 or len({int(row["outcome"]) for row in rows}) < 2:
        return None
    features = [math.log(float(row["probability"]) / (1.0 - float(row["probability"]))) for row in rows]
    outcomes = [int(row["outcome"]) for row in rows]
    intercept = math.log((sum(outcomes) + 0.5) / (len(outcomes) - sum(outcomes) + 0.5))
    slope = 1.0
    for _ in range(50):
        fitted = [1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, intercept + slope * value)))) for value in features]
        g0 = sum(outcome - probability for outcome, probability in zip(outcomes, fitted)) - regularization * intercept
        g1 = sum((outcome - probability) * value for outcome, probability, value in zip(outcomes, fitted, features)) - regularization * slope
        h00 = sum(probability * (1.0 - probability) for probability in fitted) + regularization
        h01 = sum(probability * (1.0 - probability) * value for probability, value in zip(fitted, features))
        h11 = sum(probability * (1.0 - probability) * value * value for probability, value in zip(fitted, features)) + regularization
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-12:
            return None
        delta0 = (g0 * h11 - g1 * h01) / determinant
        delta1 = (g1 * h00 - g0 * h01) / determinant
        intercept += delta0
        slope += delta1
        if max(abs(delta0), abs(delta1)) < 1e-8:
            break
    return intercept, slope


def chronological_holdout(
    samples: Iterable[dict[str, Any]],
    *,
    minimum_training_samples: int = 20,
) -> dict[str, Any]:
    rows = [row for row in _normalized(samples) if row.get("_timestamp") is not None]
    rows.sort(key=lambda row: (row["_timestamp"], str(row.get("id") or "")))
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["_timestamp"].date().isoformat()].append(row)
    training: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    skipped_dates = 0
    for date_key in sorted(by_date):
        test_rows = by_date[date_key]
        calibrator = _fit_platt(training) if len(training) >= minimum_training_samples else None
        if calibrator is None:
            skipped_dates += 1
        else:
            intercept, slope = calibrator
            prior_rate = sum(int(row["outcome"]) for row in training) / len(training)
            for row in test_rows:
                logit = math.log(float(row["probability"]) / (1.0 - float(row["probability"])))
                calibrated = 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, intercept + slope * logit))))
                predictions.append(
                    {
                        "id": row.get("id"),
                        "timestamp": row["_timestamp"].isoformat(),
                        "probability": calibrated,
                        "raw_probability": row["probability"],
                        "expanding_base_rate": prior_rate,
                        "outcome": row["outcome"],
                    }
                )
        training.extend(test_rows)
    metrics = probability_metrics(predictions)
    baseline_samples = [
        {"timestamp": row["timestamp"], "probability": row["expanding_base_rate"], "outcome": row["outcome"]}
        for row in predictions
    ]
    baseline = probability_metrics(baseline_samples)
    calibrated_brier = metrics.get("brier_score")
    baseline_brier = baseline.get("brier_score")
    return {
        "method": "expanding_window_platt_by_date",
        "minimum_training_samples": minimum_training_samples,
        "available_input_count": len(rows),
        "holdout_count": len(predictions),
        "holdout_dates": len({str(row["timestamp"])[:10] for row in predictions}),
        "skipped_warmup_dates": skipped_dates,
        "status": "ok" if len(predictions) >= 30 and metrics.get("distinct_dates", 0) >= 10 else "insufficient_holdout",
        "metrics": metrics,
        "expanding_base_rate_brier": baseline_brier,
        "brier_skill_vs_expanding_base_rate": (
            round(1.0 - calibrated_brier / baseline_brier, 6)
            if calibrated_brier is not None and baseline_brier not in {None, 0}
            else None
        ),
        "authority": "read_only_evidence_not_execution",
    }
