#!/usr/bin/env python3
"""Compare Flip entry features against forward outcomes without changing trading."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist, fmean, variance
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
TRADES_PATH = VIBE_HOME / "flip-trades.json"
REPORT_PATH = VIBE_HOME / "reports" / "flip-feature-ablation.json"
LOG_PATH = ROOT / "data" / "flip_feature_ablation_log.jsonl"

ALPHA = 0.05
MIN_TOTAL_TRADES = 30
MIN_GROUP_TRADES = 10
CATEGORICAL_FEATURES = (
    "strategy",
    "right",
    "orb_direction",
    "ttm_state",
    "shadow_consensus_recommendation",
)


def _read_trades(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_") or "unknown"


def _feature_values(snapshot: dict[str, Any]) -> dict[str, bool]:
    values: dict[str, bool] = {}
    for name, value in snapshot.items():
        if name == "schema_version":
            continue
        if isinstance(value, bool):
            values[name] = value
    for name in CATEGORICAL_FEATURES:
        value = snapshot.get(name)
        if value not in (None, ""):
            values[f"{name}__{_slug(value)}"] = True
    breadth = _number(snapshot.get("breadth_count"))
    if breadth is not None:
        values["breadth_at_least_2"] = breadth >= 2
        values["breadth_at_least_3"] = breadth >= 3
    return values


def _trade_observation(trade: dict[str, Any]) -> dict[str, Any] | None:
    if trade.get("status") != "closed":
        return None
    entry = _number(trade.get("entry_price"))
    exit_price = _number(trade.get("exit_price"))
    quality = trade.get("entry_quality")
    snapshot = quality.get("feature_snapshot") if isinstance(quality, dict) else None
    if entry is None or entry <= 0 or exit_price is None or not isinstance(snapshot, dict):
        return None
    if int(_number(snapshot.get("schema_version")) or 0) != 1:
        return None
    return {
        "trade_id": trade.get("id"),
        "return_pct": (exit_price - entry) / entry * 100,
        "features": _feature_values(snapshot),
    }


def _feature_state(features: dict[str, bool], feature: str) -> bool | None:
    if feature in features:
        return features[feature]
    if "__" in feature:
        prefix = feature.split("__", 1)[0] + "__"
        if any(name.startswith(prefix) for name in features):
            return False
    return None


def _two_sided_p_value(present: list[float], absent: list[float]) -> tuple[float | None, float | None]:
    if len(present) < 2 or len(absent) < 2:
        return None, None
    se = math.sqrt(variance(present) / len(present) + variance(absent) / len(absent))
    if se == 0:
        if fmean(present) == fmean(absent):
            return 0.0, 1.0
        return math.inf, 0.0
    z_score = (fmean(present) - fmean(absent)) / se
    p_value = 2 * (1 - NormalDist().cdf(abs(z_score)))
    return z_score, max(0.0, min(1.0, p_value))


def _bh_pass_features(rows: list[dict[str, Any]], alpha: float) -> set[str]:
    ordered = sorted(
        ((row["p_value"], row["feature"]) for row in rows if row.get("p_value") is not None),
        key=lambda item: item[0],
    )
    family_size = len(rows)
    last_rank = 0
    for rank, (p_value, _) in enumerate(ordered, 1):
        if p_value <= rank / max(1, family_size) * alpha:
            last_rank = rank
    return {name for _, name in ordered[:last_rank]}


def build_report(trades_path: Path = TRADES_PATH, alpha: float = ALPHA) -> dict[str, Any]:
    trades = _read_trades(trades_path)
    closed = [trade for trade in trades if trade.get("status") == "closed"]
    observations = [item for trade in closed if (item := _trade_observation(trade)) is not None]
    feature_names = sorted({name for item in observations for name in item["features"]})
    family_size = len(feature_names)
    bonferroni_alpha = alpha / max(1, family_size)
    rows: list[dict[str, Any]] = []

    for feature in feature_names:
        present = [item["return_pct"] for item in observations if _feature_state(item["features"], feature) is True]
        absent = [item["return_pct"] for item in observations if _feature_state(item["features"], feature) is False]
        known_count = len(present) + len(absent)
        sample_ready = (
            known_count >= MIN_TOTAL_TRADES
            and len(present) >= MIN_GROUP_TRADES
            and len(absent) >= MIN_GROUP_TRADES
        )
        z_score, p_value = _two_sided_p_value(present, absent) if sample_ready else (None, None)
        present_avg = fmean(present) if present else None
        absent_avg = fmean(absent) if absent else None
        blockers = []
        if known_count < MIN_TOTAL_TRADES:
            blockers.append("fewer_than_30_known_feature_trades")
        if len(present) < MIN_GROUP_TRADES:
            blockers.append("fewer_than_10_feature_present_trades")
        if len(absent) < MIN_GROUP_TRADES:
            blockers.append("fewer_than_10_feature_absent_trades")
        if p_value is None or p_value > bonferroni_alpha:
            blockers.append("multiple_testing_threshold_not_met")
        if present_avg is None or absent_avg is None or present_avg <= absent_avg:
            blockers.append("positive_present_group_lift_not_proven")
        rows.append({
            "feature": feature,
            "known_count": known_count,
            "present_count": len(present),
            "absent_count": len(absent),
            "present_win_rate": round(sum(value > 0 for value in present) / len(present), 4) if present else None,
            "absent_win_rate": round(sum(value > 0 for value in absent) / len(absent), 4) if absent else None,
            "present_avg_return_pct": round(present_avg, 4) if present_avg is not None else None,
            "absent_avg_return_pct": round(absent_avg, 4) if absent_avg is not None else None,
            "average_return_lift_pct_points": round(present_avg - absent_avg, 4) if present_avg is not None and absent_avg is not None else None,
            "z_score": round(z_score, 4) if z_score is not None and math.isfinite(z_score) else z_score,
            "p_value": round(p_value, 8) if p_value is not None else None,
            "bonferroni_pass": p_value is not None and p_value <= bonferroni_alpha,
            "review_blockers": blockers,
            "review_eligible": not blockers,
        })

    bh_pass = _bh_pass_features(rows, alpha)
    review_eligible = []
    for row in rows:
        row["benjamini_hochberg_pass"] = row["feature"] in bh_pass
        if row["review_eligible"]:
            review_eligible.append(row)

    return {
        "provider": "flip_feature_ablation_report",
        "mode": "read_only_descriptive_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(trades_path),
        "closed_trade_count": len(closed),
        "feature_telemetry_trade_count": len(observations),
        "insufficient_or_legacy_count": len(closed) - len(observations),
        "feature_family_count": family_size,
        "review_eligible_count": len(review_eligible),
        "multiple_testing": {
            "family_alpha": alpha,
            "bonferroni_alpha": round(bonferroni_alpha, 8),
            "benjamini_hochberg_pass_count": len(bh_pass),
            "all_observed_features_counted": True,
        },
        "review_eligible": review_eligible,
        "features": rows,
        "warnings": [
            "This is a descriptive association report, not a causal estimate or trading instruction.",
            "Legacy trades without schema-v1 entry feature telemetry remain insufficient and are never imputed.",
            "Review eligibility requires 30 known trades, 10 per group, positive lift, and Bonferroni significance.",
            "A review-eligible feature still requires an immutable OOS trial and explicit human approval before any behavior change.",
            "This report cannot promote features, change thresholds, or submit orders.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades-path", type=Path, default=TRADES_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.trades_path)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Flip feature ablation report wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
