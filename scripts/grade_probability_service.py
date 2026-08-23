#!/usr/bin/env python3
"""Fit read-only, chronological grade-to-outcome calibration mappings."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
OUTCOMES = ROOT / "data" / "shadow_outcomes.jsonl"
PATTERN_OUTCOMES = ROOT / "data" / "pattern_grader_outcomes.jsonl"
OUTPUT = ROOT / "data" / "grade_probability_calibration.json"
GRADE_SCORE = {"D": 0.0, "C": 1.0, "B": 2.0, "A": 3.0}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for raw in lines:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _isotonic(rows: list[tuple[float, int]]) -> dict[float, float]:
    grouped: dict[float, list[int]] = defaultdict(list)
    for score, outcome in rows:
        grouped[score].append(outcome)
    blocks = [{"scores": [score], "sum": float(sum(values)), "n": len(values)} for score, values in sorted(grouped.items())]
    index = 0
    while index < len(blocks) - 1:
        left = blocks[index]["sum"] / blocks[index]["n"]
        right = blocks[index + 1]["sum"] / blocks[index + 1]["n"]
        if left <= right:
            index += 1
            continue
        blocks[index:index + 2] = [{
            "scores": [*blocks[index]["scores"], *blocks[index + 1]["scores"]],
            "sum": blocks[index]["sum"] + blocks[index + 1]["sum"],
            "n": blocks[index]["n"] + blocks[index + 1]["n"],
        }]
        index = max(0, index - 1)
    mapping: dict[float, float] = {}
    for block in blocks:
        value = block["sum"] / block["n"]
        for score in block["scores"]:
            mapping[float(score)] = value
    return mapping


def _bootstrap_rate(values: list[int], *, key: str, samples: int = 500) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    block = max(5, math.ceil(math.sqrt(len(values))))
    rng = random.Random(int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16))
    estimates: list[float] = []
    for _ in range(samples):
        picked: list[int] = []
        while len(picked) < len(values):
            start = rng.randrange(len(values))
            picked.extend(values[(start + offset) % len(values)] for offset in range(block))
        estimates.append(sum(picked[: len(values)]) / len(values))
    estimates.sort()
    return estimates[int(0.025 * (len(estimates) - 1))], estimates[int(0.975 * (len(estimates) - 1))]


def _metrics(predictions: list[tuple[float, int]]) -> dict[str, Any]:
    if not predictions:
        return {"sample_size": 0, "brier_score": None, "base_rate_brier_score": None, "brier_skill_vs_expanding_base_rate": None, "ece": None, "mce": None, "reliability_bins": []}
    base = sum(outcome for _, outcome in predictions) / len(predictions)
    brier = sum((probability - outcome) ** 2 for probability, outcome in predictions) / len(predictions)
    base_brier = sum((base - outcome) ** 2 for _, outcome in predictions) / len(predictions)
    ordered = sorted(predictions)
    bins: list[dict[str, Any]] = []
    chunk = max(1, math.ceil(len(ordered) / 10))
    for start in range(0, len(ordered), chunk):
        members = ordered[start:start + chunk]
        predicted = sum(value for value, _ in members) / len(members)
        observed = sum(value for _, value in members) / len(members)
        bins.append({"count": len(members), "mean_probability": round(predicted, 4), "observed_rate": round(observed, 4), "gap": round(predicted - observed, 4)})
    ece = sum(row["count"] / len(ordered) * abs(row["gap"]) for row in bins)
    mce = max(abs(row["gap"]) for row in bins)
    return {
        "sample_size": len(predictions),
        "brier_score": round(brier, 6),
        "base_rate_brier_score": round(base_brier, 6),
        "brier_skill_vs_expanding_base_rate": round(1.0 - brier / base_brier, 6) if base_brier else None,
        "ece": round(ece, 6),
        "mce": round(mce, 6),
        "reliability_bins": bins,
    }


def build_calibration(
    outcomes: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    minimum_bucket_n: int = 30,
    maximum_ece: float = 0.15,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(hours=24)
    normalized: list[dict[str, Any]] = []
    skipped = 0
    unkeyed: list[dict[str, Any]] = []
    latest_detection: dict[str, dict[str, Any]] = {}
    for source in outcomes:
        row = dict(source)
        detection_id = str(row.get("detection_id") or "")
        if not detection_id:
            unkeyed.append(row)
            continue
        prior = latest_detection.get(detection_id)
        if prior is None or str(row.get("resolved_at") or "") >= str(prior.get("resolved_at") or ""):
            latest_detection[detection_id] = row
    for row in [*unkeyed, *latest_detection.values()]:
        stamp = _dt(row.get("resolved_at"))
        grade = str(row.get("grade") or "").upper()[:1]
        family = str(row.get("setup_family") or "").strip()
        regime = str(row.get("regime") or "").strip()
        try:
            outcome_r = float(row.get("outcome_r"))
        except (TypeError, ValueError):
            outcome_r = float("nan")
        if stamp is None or stamp > cutoff or grade not in GRADE_SCORE or not family or not regime or not math.isfinite(outcome_r):
            skipped += 1
            continue
        normalized.append({"resolved_at": stamp, "date": stamp.date().isoformat(), "family": family, "regime": regime, "grade": grade, "score": GRADE_SCORE[grade], "outcome": int(outcome_r > 0)})

    buckets: list[dict[str, Any]] = []
    group_metrics: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        grouped[(row["family"], row["regime"])].append(row)
    for (family, regime), group in sorted(grouped.items()):
        group.sort(key=lambda row: (row["resolved_at"], row["grade"]))
        prior: list[dict[str, Any]] = []
        predictions: list[tuple[float, int]] = []
        for date_key in sorted({row["date"] for row in group}):
            date_rows = [row for row in group if row["date"] == date_key]
            if len(prior) >= minimum_bucket_n and len({row["grade"] for row in prior}) >= 2:
                mapping = _isotonic([(row["score"], row["outcome"]) for row in prior])
                predictions.extend((mapping.get(row["score"], sum(item["outcome"] for item in prior) / len(prior)), row["outcome"]) for row in date_rows)
            prior.extend(date_rows)
        metrics = _metrics(predictions)
        final_mapping = _isotonic([(row["score"], row["outcome"]) for row in group])
        group_metrics.append({"setup_family": family, "regime": regime, **metrics})
        for grade in ("A", "B", "C", "D"):
            members = [row for row in group if row["grade"] == grade]
            if not members:
                continue
            outcomes_only = [row["outcome"] for row in members]
            lower, upper = _bootstrap_rate(outcomes_only, key=f"{family}|{regime}|{grade}")
            display_calibrated = len(members) >= minimum_bucket_n and metrics.get("sample_size", 0) >= minimum_bucket_n and metrics.get("ece") is not None and float(metrics["ece"]) <= maximum_ece
            ranking_qualified = display_calibrated and len(members) >= 100 and len({row["date"] for row in members}) >= 30 and (metrics.get("brier_skill_vs_expanding_base_rate") or 0.0) > 0
            status = "local_forward_validated" if ranking_qualified else "display_calibrated" if display_calibrated else "not_calibrated"
            buckets.append({
                "bucket_id": f"{family}|{regime}|{grade}",
                "setup_family": family,
                "regime": regime,
                "grade": grade,
                "probability": {
                    "value": round(final_mapping[GRADE_SCORE[grade]], 4),
                    "lower_bound": round(lower, 4) if lower is not None else None,
                    "upper_bound": round(upper, 4) if upper is not None else None,
                    "sample_size": len(members),
                    "independent_dates": len({row["date"] for row in members}),
                    "status": status,
                    "label": "Locally forward-calibrated conditional probability" if ranking_qualified else "Display calibration; not ranking-qualified" if display_calibrated else "Not calibrated",
                    "brier_skill_vs_expanding_base_rate": metrics.get("brier_skill_vs_expanding_base_rate"),
                    "ece": metrics.get("ece"),
                    "mce": metrics.get("mce"),
                },
                "calibration_status": status,
                "reliability_bins": metrics.get("reliability_bins", []),
                "execution_enabled": False,
                "can_submit_orders": False,
            })
    return {
        "schema_version": 1,
        "provider": "grade_probability_service",
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "outcome_cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "method": "expanding_date_window_isotonic_with_moving_block_bootstrap",
        "guard": {"minimum_bucket_n": minimum_bucket_n, "maximum_ece": maximum_ece, "ranking_minimum_n": 100, "ranking_minimum_dates": 30},
        "eligible_outcomes": len(normalized),
        "skipped_outcomes": skipped,
        "buckets": buckets,
        "groups": group_metrics,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", type=Path, default=OUTCOMES)
    parser.add_argument("--pattern-outcomes", type=Path, default=PATTERN_OUTCOMES)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_calibration([*_read_jsonl(args.outcomes), *_read_jsonl(args.pattern_outcomes)])
    _atomic(args.output, report)
    _atomic(VIBE_HOME / "reports" / "grade-probability-calibration.json", report)
    print(f"grade_calibration eligible={report['eligible_outcomes']} buckets={len(report['buckets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
