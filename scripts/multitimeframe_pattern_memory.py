#!/usr/bin/env python3
"""Read-only multitimeframe analog memory for directional option candidates.

The engine turns decision-time context into a normalized pattern fingerprint,
retrieves only strictly earlier resolved shadow lifecycles, and summarizes their
post-cost outcomes.  It has no execution authority and never changes strategy
configuration.  Historical analogs are retrospective evidence until a separate
forward validation promotes them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTOPSY_PATH = ROOT / "data" / "causal_trade_replay_lab_results.json"
DEFAULT_MEMORY_PATH = ROOT / "data" / "multitimeframe_pattern_memory.jsonl"
DEFAULT_REPORT_PATH = ROOT / "data" / "multitimeframe_pattern_memory_report.json"
SCHEMA_VERSION = 1
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PatternMemoryConfig:
    min_matches: int = 30
    min_independent_dates: int = 20
    max_matches: int = 75
    min_similarity: float = 0.52
    min_feature_coverage: float = 0.30
    confidence_z: float = 1.645
    additional_stress_cost_pct: float = 1.5


DISCRETE_WEIGHTS: dict[str, float] = {
    "day_type": 2.0,
    "market_force_classification": 1.5,
    "htf_primary_bias": 2.0,
    "htf_intraday_alignment": 1.5,
    "opening_range_bucket": 1.0,
    "orb_direction": 2.0,
    "orb_entry_pattern": 2.0,
    "orb_retest_status": 2.0,
    "retest_grade": 1.5,
    "candlestick_bias": 1.5,
    "candlestick_primary_signal": 1.5,
    "ttm_state": 1.0,
    "ttm_first_release": 1.0,
    "ttm_momentum_rising": 1.0,
    "above_vwap": 1.5,
    "below_vwap": 1.5,
    "above_ema50": 1.0,
    "below_ema50": 1.0,
    "ema50_sloping_up": 1.0,
    "ema50_sloping_down": 1.0,
    "pullback_held_trend": 1.5,
    "pullback_failed_near_trend": 1.5,
    "not_extended_from_vwap": 1.0,
    "catalyst_max_impact": 1.5,
    "shadow_prior_day_aligned": 1.0,
    "shadow_swept_level_name": 1.5,
    "premium_level_dominant_right": 1.0,
    "noise_area_direction": 1.0,
    "session_bucket_et": 1.0,
}

# Scale represents a materially different setup, not an optimizer parameter.
NUMERIC_SCALES: dict[str, float] = {
    "confidence": 2.0,
    "breadth_count": 2.0,
    "orb_retest_age_bars": 3.0,
    "retest_quality_score": 2.0,
    "pre_retest_extension_pct": 0.5,
    "minutes_since_breakout": 20.0,
    "retest_volume_ratio": 0.5,
    "orb_breakout_candle_atr_ratio": 0.5,
    "orb_dislocation_velocity_zscore": 1.0,
    "orb_breakout_directional_close_location_value": 0.25,
    "opening_range_fraction": 0.20,
    "expected_move_consumed_fraction": 0.20,
    "breakout_overshoot_fraction": 0.20,
    "spread_cents_at_signal": 5.0,
    "quote_age_seconds": 5.0,
    "premium_level_nearest_call_distance_pct": 0.25,
    "premium_level_nearest_put_distance_pct": 0.25,
}


_MEMORY_CACHE: dict[str, tuple[int, int, list[dict[str, Any]]]] = {}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _session_bucket(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    local = parsed.astimezone(ET)
    minute = local.hour * 60 + local.minute
    if 570 <= minute < 615:
        return "opening_0945_1015"
    if 615 <= minute < 690:
        return "late_morning_1015_1130"
    if 690 <= minute < 840:
        return "midday_1130_1400"
    if 840 <= minute < 900:
        return "afternoon_1400_1500"
    if 900 <= minute < 960:
        return "power_hour_1500_1600"
    return "outside_rth"


def _value(setup: dict[str, Any], features: dict[str, Any], key: str) -> Any:
    value = features.get(key)
    return value if value is not None else setup.get(key)


def _direction(right: Any) -> str:
    normalized = str(right or "").upper()
    return "bullish" if normalized == "CALL" else "bearish" if normalized == "PUT" else "unknown"


def _structure_sequence(discrete: dict[str, Any]) -> list[str]:
    ordered = (
        ("htf", "htf_primary_bias"),
        ("day", "day_type"),
        ("range", "opening_range_bucket"),
        ("break", "orb_direction"),
        ("setup", "orb_entry_pattern"),
        ("retest", "orb_retest_status"),
        ("candle", "candlestick_primary_signal"),
        ("vwap", "above_vwap"),
        ("vwap", "below_vwap"),
        ("squeeze", "ttm_state"),
    )
    return [f"{label}:{discrete[key]}" for label, key in ordered if key in discrete]


def build_fingerprint(
    setup: dict[str, Any],
    *,
    feature_snapshot: dict[str, Any] | None = None,
    observed_at: Any = None,
) -> dict[str, Any]:
    """Create a scale-normalized, decision-time-only setup representation."""
    features = feature_snapshot if isinstance(feature_snapshot, dict) else {}
    right = str(_value(setup, features, "right") or "").upper()
    strategy = str(_value(setup, features, "strategy") or "unknown").lower()
    symbol = str(setup.get("symbol") or "SPY").upper()
    discrete: dict[str, Any] = {}
    for key in DISCRETE_WEIGHTS:
        raw = _value(setup, features, key)
        if isinstance(raw, bool):
            discrete[key] = raw
        elif (normalized := _text(raw)) is not None:
            discrete[key] = normalized
    bucket = _text(_value(setup, features, "episode_bucket_et")) or _session_bucket(
        observed_at or setup.get("entry_at") or setup.get("scanned_at")
    )
    if bucket:
        discrete["session_bucket_et"] = bucket

    numeric: dict[str, float] = {}
    for key in NUMERIC_SCALES:
        if (parsed := _finite(_value(setup, features, key))) is not None:
            numeric[key] = round(parsed, 6)

    frames = {
        "daily": {
            "bias": discrete.get("htf_primary_bias"),
            "catalyst": discrete.get("catalyst_max_impact"),
        },
        "hourly": {
            "day_type": discrete.get("day_type"),
            "market_force": discrete.get("market_force_classification"),
        },
        "15m": {
            "opening_range": discrete.get("opening_range_bucket"),
            "break_direction": discrete.get("orb_direction"),
        },
        "5m": {
            "entry_pattern": discrete.get("orb_entry_pattern"),
            "retest": discrete.get("orb_retest_status"),
            "candlestick": discrete.get("candlestick_primary_signal"),
        },
        "1m_execution": {
            "retest_grade": discrete.get("retest_grade"),
            "vwap_above": discrete.get("above_vwap"),
            "vwap_below": discrete.get("below_vwap"),
        },
    }
    identity = {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "strategy": strategy,
        "right": right,
        "discrete": discrete,
        "numeric_bucket": {
            key: round(value / NUMERIC_SCALES[key], 1) for key, value in numeric.items()
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "pattern_id": hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24],
        "symbol": symbol,
        "strategy": strategy,
        "right": right,
        "direction": _direction(right),
        "frames": frames,
        "discrete": discrete,
        "numeric": numeric,
        "structure_sequence": _structure_sequence(discrete),
    }


def _lcs_ratio(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.5
    previous = [0] * (len(right) + 1)
    for lval in left:
        current = [0]
        for idx, rval in enumerate(right, start=1):
            current.append(previous[idx - 1] + 1 if lval == rval else max(previous[idx], current[-1]))
        previous = current
    return previous[-1] / max(len(left), len(right))


def fingerprint_similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
    """Return similarity and candidate-feature coverage in [0, 1]."""
    for key in ("symbol", "strategy", "right"):
        if left.get(key) and right.get(key) and left[key] != right[key]:
            return 0.0, 0.0

    left_discrete = left.get("discrete") or {}
    right_discrete = right.get("discrete") or {}
    compared_weight = 0.0
    mismatch_weight = 0.0
    candidate_weight = sum(DISCRETE_WEIGHTS[key] for key in left_discrete if key in DISCRETE_WEIGHTS)
    for key, weight in DISCRETE_WEIGHTS.items():
        if key not in left_discrete or key not in right_discrete:
            continue
        compared_weight += weight
        mismatch_weight += weight * (left_discrete[key] != right_discrete[key])
    discrete_distance = mismatch_weight / compared_weight if compared_weight else 0.5

    left_numeric = left.get("numeric") or {}
    right_numeric = right.get("numeric") or {}
    numeric_distances = [
        min(1.0, abs(float(left_numeric[key]) - float(right_numeric[key])) / NUMERIC_SCALES[key])
        for key in NUMERIC_SCALES
        if key in left_numeric and key in right_numeric
    ]
    numeric_distance = statistics.fmean(numeric_distances) if numeric_distances else 0.5
    candidate_numeric = sum(key in left_numeric for key in NUMERIC_SCALES)
    compared_numeric = len(numeric_distances)
    denominator = candidate_weight + candidate_numeric
    coverage = (
        (compared_weight + compared_numeric) / denominator if denominator > 0 else 0.0
    )
    sequence_similarity = _lcs_ratio(
        list(left.get("structure_sequence") or []),
        list(right.get("structure_sequence") or []),
    )
    distance = 0.60 * discrete_distance + 0.25 * numeric_distance + 0.15 * (1.0 - sequence_similarity)
    similarity = max(0.0, 1.0 - distance) * (0.65 + 0.35 * coverage)
    return round(similarity, 6), round(coverage, 6)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _outcome_stats(rows: list[dict[str, Any]], config: PatternMemoryConfig) -> dict[str, Any]:
    returns = [value for row in rows if (value := _finite((row.get("outcome") or {}).get("net_return_pct"))) is not None]
    mfes = [value for row in rows if (value := _finite((row.get("outcome") or {}).get("mfe_post_cost_pct"))) is not None]
    maes = [value for row in rows if (value := _finite((row.get("outcome") or {}).get("mae_post_cost_pct"))) is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    mean = statistics.fmean(returns) if returns else 0.0
    stdev = statistics.stdev(returns) if len(returns) > 1 else 0.0
    se = stdev / math.sqrt(len(returns)) if returns else math.inf
    lower = mean - config.confidence_z * se if math.isfinite(se) else None
    upper = mean + config.confidence_z * se if math.isfinite(se) else None
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "matches": len(returns),
        "independent_dates": len({str(row.get("date") or "") for row in rows if row.get("date")}),
        "expectancy_post_cost_pct": round(mean, 4),
        "median_post_cost_pct": round(statistics.median(returns), 4) if returns else None,
        "win_rate": round(len(wins) / len(returns), 4) if returns else None,
        # Keep persisted JSON standards-compliant; 999 denotes no observed loss.
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else None),
        "confidence_interval_90_pct": [round(lower, 4), round(upper, 4)] if lower is not None else None,
        "stress_expectancy_pct": round(mean - config.additional_stress_cost_pct, 4),
        "median_mfe_post_cost_pct": round(statistics.median(mfes), 4) if mfes else None,
        "median_mae_post_cost_pct": round(statistics.median(maes), 4) if maes else None,
        "mfe_25th_pct": round(_percentile(mfes, 0.25), 4) if mfes else None,
        "mae_25th_pct": round(_percentile(maes, 0.25), 4) if maes else None,
    }


def _advice_from_records(
    fingerprint: dict[str, Any],
    records: Iterable[dict[str, Any]],
    *,
    as_of_date: date,
    config: PatternMemoryConfig,
) -> dict[str, Any]:
    matches: list[tuple[float, float, dict[str, Any]]] = []
    excluded_not_prior = 0
    for record in records:
        try:
            record_date = date.fromisoformat(str(record.get("date") or ""))
        except ValueError:
            continue
        if record_date >= as_of_date:
            excluded_not_prior += 1
            continue
        candidate = record.get("fingerprint") if isinstance(record.get("fingerprint"), dict) else {}
        similarity, coverage = fingerprint_similarity(fingerprint, candidate)
        if similarity >= config.min_similarity and coverage >= config.min_feature_coverage:
            matches.append((similarity, coverage, record))
    matches.sort(key=lambda item: (item[0], item[2].get("date") or ""), reverse=True)
    selected = matches[: config.max_matches]
    rows = [item[2] for item in selected]
    stats = _outcome_stats(rows, config)
    review_ready = (
        stats["matches"] >= config.min_matches
        and stats["independent_dates"] >= config.min_independent_dates
    )
    interval = stats.get("confidence_interval_90_pct") or [None, None]
    lower, upper = interval
    if not review_ready:
        status = "insufficient_history"
    elif lower is not None and lower > 0 and stats["stress_expectancy_pct"] > 0 and (stats["profit_factor"] or 0) > 1:
        status = "positive_edge"
    elif upper is not None and upper < 0:
        status = "negative_edge"
    else:
        status = "ambiguous"
    examples = [
        {
            "lifecycle_id": row.get("lifecycle_id"),
            "date": row.get("date"),
            "similarity": similarity,
            "coverage": coverage,
            "net_return_pct": (row.get("outcome") or {}).get("net_return_pct"),
        }
        for similarity, coverage, row in selected[:5]
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "pattern_id": fingerprint.get("pattern_id"),
        "as_of_date": as_of_date.isoformat(),
        "strictly_prior_date_only": True,
        "same_day_or_future_records_excluded": excluded_not_prior,
        "analog_summary": stats,
        "review_ready": review_ready,
        "forward_validated": False,
        "evidence_status": "retrospective_consumed_corpus_requires_forward_validation",
        "diagnostic_exit_envelope": {
            "target_reference_pct": stats.get("mfe_25th_pct"),
            "adverse_excursion_reference_pct": stats.get("mae_25th_pct"),
            "authority": "diagnostic_only_not_an_exit_command",
        },
        "closest_analogs": examples,
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_size": False,
        "can_block_entry": False,
        "authority": "shadow_advisory_only",
    }


def load_memory(path: Path = DEFAULT_MEMORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    stat = path.stat()
    key = str(path.resolve())
    cached = _MEMORY_CACHE.get(key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    _MEMORY_CACHE[key] = (stat.st_mtime_ns, stat.st_size, rows)
    return rows


def advise_setup(
    setup: dict[str, Any],
    *,
    feature_snapshot: dict[str, Any] | None = None,
    memory_path: Path = DEFAULT_MEMORY_PATH,
    as_of: datetime | date | None = None,
    config: PatternMemoryConfig = PatternMemoryConfig(),
    records: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    observed = as_of or datetime.now(timezone.utc)
    as_of_date = observed if isinstance(observed, date) and not isinstance(observed, datetime) else observed.date()
    fingerprint = build_fingerprint(setup, feature_snapshot=feature_snapshot, observed_at=observed)
    memory = list(records) if records is not None else load_memory(memory_path)
    advice = _advice_from_records(fingerprint, memory, as_of_date=as_of_date, config=config)
    advice["memory_records_available"] = len(memory)
    advice["fingerprint"] = fingerprint
    return advice


def build_records_from_autopsies(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in payload.get("trade_autopsies") or []:
        if not isinstance(row, dict):
            continue
        outcome = _finite(row.get("baseline_return_pct"))
        if outcome is None or not row.get("date"):
            continue
        features = row.get("entry_features") if isinstance(row.get("entry_features"), dict) else {}
        setup = {
            "symbol": row.get("symbol"),
            "strategy": row.get("strategy"),
            "right": row.get("right"),
            "entry_at": row.get("entry_at"),
            "day_type": row.get("day_type"),
        }
        records.append({
            "schema_version": SCHEMA_VERSION,
            "lifecycle_id": row.get("lifecycle_id"),
            "date": str(row.get("date")),
            "entry_at": row.get("entry_at"),
            "fingerprint": build_fingerprint(setup, feature_snapshot=features, observed_at=row.get("entry_at")),
            "outcome": {
                "net_return_pct": outcome,
                "mfe_post_cost_pct": _finite(row.get("mfe_post_fee_pct")),
                "mae_post_cost_pct": _finite(row.get("mae_post_fee_pct")),
                "exit_reason": row.get("baseline_exit_reason"),
                "diagnosis": row.get("diagnosis"),
            },
            "provenance": "causal_trade_replay_lab_resolved_shadow_lifecycle",
        })
    records.sort(key=lambda row: (row["date"], str(row.get("entry_at") or ""), str(row.get("lifecycle_id") or "")))
    return records


def evaluate_walk_forward(
    records: list[dict[str, Any]],
    *,
    config: PatternMemoryConfig = PatternMemoryConfig(),
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    dates = sorted({str(row.get("date")) for row in records if row.get("date")})
    for current_date in dates:
        day = date.fromisoformat(current_date)
        history = [row for row in records if str(row.get("date")) < current_date]
        for row in (item for item in records if item.get("date") == current_date):
            advice = _advice_from_records(row["fingerprint"], history, as_of_date=day, config=config)
            decisions.append({
                "date": current_date,
                "lifecycle_id": row.get("lifecycle_id"),
                "status": advice["status"],
                "review_ready": advice["review_ready"],
                "predicted_expectancy_pct": advice["analog_summary"]["expectancy_post_cost_pct"],
                "realized_return_pct": (row.get("outcome") or {}).get("net_return_pct"),
            })
    positive = [row for row in decisions if row["status"] == "positive_edge"]
    realized = [float(row["realized_return_pct"]) for row in positive if _finite(row.get("realized_return_pct")) is not None]
    return {
        "dates": len(dates),
        "decisions": len(decisions),
        "status_counts": {status: sum(row["status"] == status for row in decisions) for status in sorted({row["status"] for row in decisions})},
        "positive_edge_oos": _outcome_stats(
            [{"date": row["date"], "outcome": {"net_return_pct": row["realized_return_pct"]}} for row in positive],
            config,
        ) if positive else {"matches": 0, "independent_dates": 0},
        "positive_edge_realized_returns": len(realized),
        "strict_chronology": True,
        "execution_authority": "none_research_replay_only",
    }


def rebuild_memory(
    source: Path = DEFAULT_AUTOPSY_PATH,
    output: Path = DEFAULT_MEMORY_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    records = build_records_from_autopsies(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in records:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": str(source),
        "memory": str(output),
        "records": len(records),
        "date_range": [records[0]["date"], records[-1]["date"]] if records else [],
        "walk_forward": evaluate_walk_forward(records),
        "execution_enabled": False,
        "can_submit_orders": False,
        "authority": "research_and_shadow_advisory_only",
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_AUTOPSY_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_MEMORY_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    report = rebuild_memory(args.source, args.out, args.report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
