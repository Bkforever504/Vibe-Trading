#!/usr/bin/env python3
"""Measure radar discovery and ranking against the frozen move denominator."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
MISSED_LEDGER = ROOT / "data" / "missed_move_postmortem.jsonl"
PATTERN_GRADER_LOG = ROOT / "data" / "pattern_grader_log.jsonl"
PATTERN_TAXONOMY = ROOT / "research" / "pattern_taxonomy.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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


def _stamp(row: dict[str, Any]) -> str | None:
    value = row.get("as_of_et") or row.get("generated_at")
    return str(value) if value else None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _taxonomy_families(path: Path = PATTERN_TAXONOMY) -> dict[str, str]:
    return {
        str(row.get("id")): str(row.get("family") or "unclassified")
        for row in _read_json(path).get("patterns") or []
        if isinstance(row, dict) and row.get("id")
    }


def _pattern_id(row: dict[str, Any]) -> str | None:
    nested = row.get("pattern") if isinstance(row.get("pattern"), dict) else {}
    value = row.get("pattern_id") or row.get("setup_id") or nested.get("id")
    return str(value) if value else None


def _pattern_family(row: dict[str, Any], families: dict[str, str]) -> str:
    nested = row.get("pattern") if isinstance(row.get("pattern"), dict) else {}
    pattern_id = _pattern_id(row)
    return str(row.get("family") or row.get("setup_family") or nested.get("family") or families.get(pattern_id or "") or "unclassified")


def _pattern_labels(move: dict[str, Any], families: dict[str, str]) -> list[tuple[str, str]]:
    raw: list[Any] = []
    raw.extend(move.get("pattern_labels") or [])
    raw.extend(move.get("pattern_ids") or [])
    if move.get("pattern_id"):
        raw.append(move["pattern_id"])
    labels: list[tuple[str, str]] = []
    for value in raw:
        if isinstance(value, dict):
            pattern_id = _pattern_id(value)
            family = _pattern_family(value, families)
        else:
            pattern_id = str(value) if value else None
            family = families.get(pattern_id or "", "unclassified")
        if pattern_id and (pattern_id, family) not in labels:
            labels.append((pattern_id, family))
    return labels


def _row_date(row: dict[str, Any]) -> str:
    return str(
        row.get("date")
        or row.get("session_date")
        or row.get("ts_utc")
        or row.get("bar_id")
        or row.get("resolved_at")
        or row.get("generated_at")
        or ""
    )[:10]


def _outcome(row: dict[str, Any]) -> float | None:
    value: Any = row.get("outcome")
    if value is None:
        value = row.get("outcome_eod") or row.get("outcome_60m") or row.get("outcome_15m") or row.get("outcome_5m")
    if isinstance(value, dict):
        if value.get("won") is not None:
            value = value.get("won")
        elif value.get("realized_r") is not None:
            value = value.get("realized_r")
        else:
            value = value.get("outcome_r")
    if value is None:
        value = row.get("won")
    if value is None:
        value = row.get("outcome_r")
    if isinstance(value, bool):
        return float(value)
    number = _number(value)
    return None if number is None else float(number > 0)


def _probability(row: dict[str, Any]) -> float | None:
    value: Any = row.get("probability")
    if isinstance(value, dict):
        value = next((value.get(key) for key in ("value", "win", "win_probability") if value.get(key) is not None), None)
    if value is None:
        value = next((row.get(key) for key in ("win_probability", "probability_win") if row.get(key) is not None), None)
    number = _number(value)
    if number is None:
        return None
    number = number / 100.0 if number > 1.0 else number
    return number if 0.0 <= number <= 1.0 else None


def build_pattern_coverage(
    ground_truth: dict[str, Any],
    pattern_grader_rows: Iterable[dict[str, Any]],
    *,
    families: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compare causal grader detections with separately labeled truth patterns."""
    family_map = families or _taxonomy_families()
    date_key = str(ground_truth.get("date") or "")[:10]
    truth: set[tuple[str, str, str]] = set()
    truth_family: dict[tuple[str, str, str], str] = {}
    for move in ground_truth.get("moves") or []:
        if not isinstance(move, dict):
            continue
        symbol = str(move.get("symbol") or "").upper()
        for pattern_id, family in _pattern_labels(move, family_map):
            key = (date_key, symbol, pattern_id)
            truth.add(key)
            truth_family[key] = family

    detections: set[tuple[str, str, str]] = set()
    detection_family: dict[tuple[str, str, str], str] = {}
    usable_rows: list[dict[str, Any]] = []
    for row in pattern_grader_rows:
        if not isinstance(row, dict) or row.get("detected") is False:
            continue
        row_date = _row_date(row)
        if date_key and row_date != date_key:
            continue
        pattern_id = _pattern_id(row)
        symbol = str(row.get("symbol") or row.get("instrument") or "").upper()
        if not pattern_id or not symbol:
            continue
        key = (row_date, symbol, pattern_id)
        detections.add(key)
        detection_family[key] = _pattern_family(row, family_map)
        usable_rows.append(row)

    pattern_ids = sorted({key[2] for key in truth | detections})
    per_pattern: list[dict[str, Any]] = []
    for pattern_id in pattern_ids:
        pattern_truth = {key for key in truth if key[2] == pattern_id}
        pattern_detected = {key for key in detections if key[2] == pattern_id}
        hits = pattern_truth & pattern_detected
        per_pattern.append({
            "pattern_id": pattern_id,
            "family": family_map.get(pattern_id) or next((detection_family[key] for key in pattern_detected), "unclassified"),
            "ground_truth_labeled": len(pattern_truth),
            "grader_detected": len(pattern_detected),
            "true_positives": len(hits),
            "false_positives": len(pattern_detected - pattern_truth),
            "false_negatives": len(pattern_truth - pattern_detected),
            "precision": round(len(hits) / len(pattern_detected), 4) if pattern_detected else None,
            "recall": round(len(hits) / len(pattern_truth), 4) if pattern_truth else None,
            "coverage_delta": len(pattern_detected) - len(pattern_truth),
        })

    per_family: list[dict[str, Any]] = []
    for family in sorted({row["family"] for row in per_pattern}):
        rows = [row for row in per_pattern if row["family"] == family]
        labeled = sum(row["ground_truth_labeled"] for row in rows)
        detected = sum(row["grader_detected"] for row in rows)
        hits = sum(row["true_positives"] for row in rows)
        per_family.append({
            "family": family,
            "ground_truth_labeled": labeled,
            "grader_detected": detected,
            "true_positives": hits,
            "false_positives": sum(row["false_positives"] for row in rows),
            "false_negatives": sum(row["false_negatives"] for row in rows),
            "precision": round(hits / detected, 4) if detected else None,
            "recall": round(hits / labeled, 4) if labeled else None,
            "coverage_delta": detected - labeled,
        })

    cisd_rows = [row for row in usable_rows if _pattern_id(row) == "ict_cisd_universal_model"]
    resolved = [row for row in cisd_rows if _outcome(row) is not None]
    scored = [(_probability(row), _outcome(row)) for row in resolved]
    scored = [(probability, outcome) for probability, outcome in scored if probability is not None and outcome is not None]
    qualified = bool(ground_truth.get("metrics_qualified"))
    return {
        "status": "measured" if qualified else "placeholder_pending_kenny_signoff",
        "metrics_qualified": qualified,
        "source_labels": ["data/pattern_grader_log.jsonl", "move_universe_ground_truth"],
        "totals": {
            "ground_truth_labeled": len(truth),
            "grader_detected": len(detections),
            "true_positives": len(truth & detections),
            "coverage_delta": len(detections) - len(truth),
        },
        "per_pattern": per_pattern,
        "per_family": per_family,
        "cisd_hypothesis": {
            "pattern_id": "ict_cisd_universal_model",
            "n_outcomes": len(resolved),
            "n_dates": len({_row_date(row) for row in resolved if _row_date(row)}),
            "brier": round(sum((probability - outcome) ** 2 for probability, outcome in scored) / len(scored), 6) if scored else None,
            "scored_outcomes": len(scored),
            "status": "measured" if resolved else "awaiting_resolved_outcomes",
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_scorecard(
    ground_truth: dict[str, Any],
    radar_history: Iterable[dict[str, Any]],
    *,
    k: int = 10,
    regime: str = "unavailable",
    pattern_grader_rows: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    date_key = str(ground_truth.get("date") or "")[:10]
    snapshots = sorted(
        (row for row in radar_history if str(row.get("date") or "")[:10] == date_key),
        key=lambda row: _stamp(row) or "",
    )
    first_discovered: dict[str, str] = {}
    first_ranked: dict[str, dict[str, Any]] = {}
    final_top_k: list[str] = []
    for snapshot in snapshots:
        stamp = _stamp(snapshot)
        for symbol in snapshot.get("all_discovered_symbols") or []:
            if stamp:
                first_discovered.setdefault(str(symbol).upper(), stamp)
        ranked = [row for row in snapshot.get("ranked_candidates") or [] if isinstance(row, dict) and row.get("symbol")]
        final_top_k = [str(row["symbol"]).upper() for row in ranked[:k]]
        for rank, candidate in enumerate(ranked, 1):
            symbol = str(candidate["symbol"]).upper()
            if stamp and symbol not in first_ranked:
                first_ranked[symbol] = {"timestamp": stamp, "rank": rank, "candidate": candidate}

    moves: list[dict[str, Any]] = []
    for truth in ground_truth.get("moves") or []:
        if not isinstance(truth, dict):
            continue
        symbol = str(truth.get("symbol") or "").upper()
        ranked = first_ranked.get(symbol)
        discovered_at = first_discovered.get(symbol)
        move_start = _dt(truth.get("move_start_at"))
        first_surface = _dt((ranked or {}).get("timestamp") or discovered_at)
        latency_bars = None
        if move_start and first_surface:
            latency_bars = max(0, math.ceil((first_surface - move_start).total_seconds() / 300.0))
        if not discovered_at and not ranked:
            partition = "discovery_miss"
        elif not ranked:
            partition = "ranking_miss"
        elif int(ranked["rank"]) > k:
            partition = "ranking_miss"
        elif latency_bars is not None and latency_bars > 3:
            partition = "late_alert"
        else:
            candidate = ranked["candidate"]
            partition = "correct_entry" if str(candidate.get("direction")) == str(truth.get("direction")) else "false_positive"
        moves.append({
            **truth,
            "first_discovered_at": discovered_at,
            "first_ranked_at": (ranked or {}).get("timestamp"),
            "first_rank": (ranked or {}).get("rank"),
            "discovery_latency_bars": latency_bars,
            "partition": partition,
            "regime": regime,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    truth_symbols = {str(row.get("symbol") or "").upper() for row in moves}
    recalled = {str(row["symbol"]).upper() for row in moves if row.get("first_rank") is not None and int(row["first_rank"]) <= k}
    precision_hits = truth_symbols.intersection(final_top_k)
    latencies = [int(row["discovery_latency_bars"]) for row in moves if row.get("discovery_latency_bars") is not None]
    counts: dict[str, int] = {}
    for row in moves:
        counts[str(row["partition"])] = counts.get(str(row["partition"]), 0) + 1
    metrics = {
        "k": k,
        "ground_truth_count": len(moves),
        "recall_at_k": round(len(recalled) / len(moves), 4) if moves else None,
        "precision_at_k": round(len(precision_hits) / len(final_top_k), 4) if final_top_k else None,
        "median_discovery_latency_bars": sorted(latencies)[len(latencies) // 2] if latencies else None,
        "partition_counts": counts,
        "snapshots_reviewed": len(snapshots),
    }
    pattern_coverage = build_pattern_coverage(ground_truth, pattern_grader_rows)
    return {
        "schema_version": 1,
        "provider": "detection_scorecard",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": date_key,
        "metrics": metrics,
        "ground_truth_status": ground_truth.get("ground_truth_status", "legacy_unspecified"),
        "metrics_qualified": bool(ground_truth.get("metrics_qualified", True)),
        "pattern_coverage": pattern_coverage,
        "per_regime": {regime: metrics},
        "latency_histogram": [{"bars": value, "count": latencies.count(value)} for value in sorted(set(latencies))],
        "moves": moves,
        "missed_moves": [row for row in moves if row["partition"] in {"discovery_miss", "ranking_miss", "late_alert"}],
        "warnings": ["Recall and precision measure detection, not profitability or executable edge."],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_rolling(reports: Iterable[dict[str, Any]], *, window: int = 30) -> dict[str, Any]:
    rows = sorted((row for row in reports if row.get("metrics")), key=lambda row: str(row.get("date") or ""))[-window:]
    truth = sum(int(row["metrics"].get("ground_truth_count") or 0) for row in rows)
    recalled = sum(
        sum(1 for move in row.get("moves") or [] if move.get("first_rank") is not None and int(move["first_rank"]) <= int(row["metrics"].get("k") or 10))
        for row in rows
    )
    final_precision_values = [float(row["metrics"]["precision_at_k"]) for row in rows if row["metrics"].get("precision_at_k") is not None]
    missed = [move for row in rows for move in row.get("missed_moves") or []]
    latest_pattern = rows[-1].get("pattern_coverage", {}) if rows else {}
    return {
        "schema_version": 1,
        "provider": "detection_scorecard_rolling",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sessions": len(rows),
        "metrics": {
            "recall_at_10": round(recalled / truth, 4) if truth else None,
            "precision_at_10_mean": round(sum(final_precision_values) / len(final_precision_values), 4) if final_precision_values else None,
            "ground_truth_count": truth,
            "root_cause_coverage": round(sum(bool(move.get("partition")) for move in missed) / len(missed), 4) if missed else None,
        },
        "top_missed_moves": sorted(missed, key=lambda row: abs(float(row.get("move_pct") or 0.0)), reverse=True)[:10],
        "daily": [{"date": row.get("date"), **row.get("metrics", {})} for row in rows],
        "pattern_coverage": latest_pattern,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _append_postmortems(path: Path, rows: list[dict[str, Any]]) -> None:
    existing = {str(row.get("move_id")) for row in _read_jsonl(path)}
    additions = [
        {
            "schema_version": 1,
            "move_id": row.get("move_id"),
            "date": row.get("date"),
            "symbol": row.get("symbol"),
            "move_pct": row.get("move_pct"),
            "reason_class": row.get("partition"),
            "fix_hypothesis": "requires_preregistered_change_before_any_filter_or_rank_adjustment",
            "double_count_review": "required",
            "source_report": f"data/detection_scorecard_{str(row.get('date') or '').replace('-', '')}.json",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        for row in rows
        if str(row.get("move_id")) not in existing
    ]
    if not additions:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in additions:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--radar-log", type=Path, default=RADAR_LOG)
    parser.add_argument("--pattern-grader-log", type=Path, default=PATTERN_GRADER_LOG)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    compact = args.date.replace("-", "")
    ground = _read_json(args.data_dir / f"move_ground_truth_{compact}.json")
    report = build_scorecard(
        ground,
        _read_jsonl(args.radar_log),
        k=args.k,
        pattern_grader_rows=_read_jsonl(args.pattern_grader_log),
    )
    daily_path = args.data_dir / f"detection_scorecard_{compact}.json"
    _atomic(daily_path, report)
    reports = [_read_json(path) for path in args.data_dir.glob("detection_scorecard_????????.json")]
    rolling = build_rolling(reports)
    _atomic(args.data_dir / "detection_scorecard_rolling.json", rolling)
    _atomic(VIBE_HOME / "reports" / "detection-scorecard-rolling.json", rolling)
    if report["metrics_qualified"]:
        _append_postmortems(args.data_dir / "missed_move_postmortem.jsonl", report["missed_moves"])
    print(f"detection_scorecard date={args.date} recall@{args.k}={report['metrics']['recall_at_k']} truth={report['metrics']['ground_truth_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
