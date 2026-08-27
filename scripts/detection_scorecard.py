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
PATTERN_GRADER_OUTCOMES = ROOT / "data" / "pattern_grader_outcomes.jsonl"
PATTERN_TAXONOMY = ROOT / "research" / "pattern_taxonomy.json"
MAX_PRIOR_SNAPSHOT_AGE_MINUTES = 15.0


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


STAGE_DEFINITIONS = {
    "market_move": "A distinct, qualifying retrospective move window exists in covered market data.",
    "discovered": "The symbol was present in the nearest radar snapshot at or before the move window began.",
    "setup_confirmed": "That linked radar snapshot contained a mechanically confirmed setup for the symbol.",
    "execution_qualified": "That linked snapshot placed the symbol in the execution-qualified ranking; this is not a fill or order claim.",
}


def _symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("instrument") or "").upper()


def _direction(value: Any) -> str:
    direction = str(value or "").lower()
    if direction in {"long", "bull", "up", "1", "+1"}:
        return "bullish"
    if direction in {"short", "bear", "down", "-1"}:
        return "bearish"
    return direction


def _move_start(row: dict[str, Any]) -> datetime | None:
    return _dt(row.get("move_start_at") or row.get("trigger_bar_ts") or row.get("bar_close_ts"))


def _candidate_confirmed(candidate: dict[str, Any] | None) -> bool:
    if not candidate:
        return False
    if "confirmation_stage" in candidate:
        stage = str(candidate.get("confirmation_stage") or "").lower()
        return stage == "completed_5m_confirmed" or stage.endswith("_confirmed")
    if candidate.get("setup_confirmed") is True or candidate.get("confirmed") is True:
        return True
    confirmation = candidate.get("price_action_confirmation")
    structure = candidate.get("structure")
    values = [
        (confirmation or {}).get("state") if isinstance(confirmation, dict) else None,
        (structure or {}).get("price_action_state") if isinstance(structure, dict) else None,
    ]
    if any(str(value or "").lower().endswith("_confirmed") for value in values):
        return True
    # Older radar snapshots had no explicit confirmation object. Their watch
    # states were only reached after the then-current setup confirmation gates.
    return str(candidate.get("state") or "") in {"watch", "precision_watch"}


def _snapshot_candidates(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        row for row in snapshot.get(key) or []
        if isinstance(row, dict) and _symbol(row)
    ]


def _lane_ranked_entries(
    snapshot: dict[str, Any], key: str
) -> list[tuple[int, dict[str, Any], str]]:
    """Return comparable ranks within benchmark and broad-mover lanes."""
    benchmark_lane = snapshot.get("benchmark_lane")
    benchmark_lane = benchmark_lane if isinstance(benchmark_lane, dict) else {}
    benchmark = _snapshot_candidates(benchmark_lane, key)
    benchmark_symbols = {
        str(value).upper() for value in benchmark_lane.get("symbols") or []
    }
    broad = [
        row for row in _snapshot_candidates(snapshot, key)
        if _symbol(row) not in benchmark_symbols
    ]
    entries = [
        (int(row.get("lane_rank") or rank), row, "benchmark")
        for rank, row in enumerate(benchmark, 1)
    ]
    entries.extend((rank, row, "broad_mover") for rank, row in enumerate(broad, 1))
    return entries


def _nearest_prior_link(
    truth: dict[str, Any], snapshots: list[dict[str, Any]]
) -> dict[str, Any]:
    """Link one hindsight label to the last observation available before it.

    The linkage is counterfactual measurement only. It never assumes that a
    displayed candidate was filled or that an order could have been submitted.
    """
    start = _move_start(truth)
    symbol = _symbol(truth)
    prior = [row for row in snapshots if _dt(_stamp(row)) and start and _dt(_stamp(row)) <= start]
    snapshot = prior[-1] if prior else None
    snapshot_at = _dt(_stamp(snapshot or {}))
    ranked_entries = _lane_ranked_entries(snapshot or {}, "ranked_candidates")
    actionable_key_present = bool(
        snapshot is not None
        and (
            "actionable_ranked_candidates" in snapshot
            or "actionable_ranked_candidates" in (snapshot.get("benchmark_lane") or {})
        )
    )
    actionable_entries = _lane_ranked_entries(snapshot or {}, "actionable_ranked_candidates")
    ranked_match = next(((rank, row, lane) for rank, row, lane in ranked_entries if _symbol(row) == symbol), None)
    actionable_match = next(((rank, row, lane) for rank, row, lane in actionable_entries if _symbol(row) == symbol), None)
    discovered = bool(
        snapshot
        and (
            symbol in {_symbol({"symbol": value}) for value in snapshot.get("all_discovered_symbols") or []}
            or ranked_match
            or actionable_match
        )
    )
    candidate = (ranked_match or actionable_match or (None, None, None))[1]
    setup_confirmed = _candidate_confirmed(candidate)
    execution_qualified = bool(
        setup_confirmed
        and (
            actionable_match
            or (
            not actionable_key_present
            and candidate
            and str(candidate.get("state") or "") in {"watch", "precision_watch"}
            and not [
                value for value in candidate.get("blockers") or []
                if str(value) != "strategy_confirmation_and_revalidation_required"
            ]
            )
        )
    )
    signed_latency = None
    lead_minutes = None
    if start and snapshot_at:
        signed_latency = round((snapshot_at - start).total_seconds() / 60.0, 2)
        lead_minutes = round(-signed_latency, 2)
    stale_snapshot = bool(
        snapshot_at
        and start
        and (start - snapshot_at).total_seconds() / 60.0 > MAX_PRIOR_SNAPSHOT_AGE_MINUTES
    )
    candidate_direction = _direction((candidate or {}).get("direction"))
    truth_direction = _direction(truth.get("direction") or truth.get("label"))
    if stale_snapshot:
        return {
            "status": "stale_prior_snapshot",
            "radar_snapshot_at": _stamp(snapshot or {}),
            "move_start_at": start.isoformat().replace("+00:00", "Z") if start else None,
            "latency_minutes": signed_latency,
            "snapshot_lead_minutes": lead_minutes,
            "max_snapshot_age_minutes": MAX_PRIOR_SNAPSHOT_AGE_MINUTES,
            "stale_rank": (ranked_match or (None,))[0],
            "stale_execution_rank": (actionable_match or (None,))[0],
            "rank": None,
            "execution_rank": None,
            "ranking_lane": (ranked_match or actionable_match or (None, None, None))[2],
            "candidate_direction": candidate_direction or None,
            "direction_correct": None,
            "stages": {
                "market_move": True,
                "discovered": False,
                "setup_confirmed": False,
                "execution_qualified": False,
            },
            "fill_assumed": False,
        }
    return {
        "status": "linked_nearest_prior_snapshot" if snapshot else "no_prior_snapshot",
        "radar_snapshot_at": _stamp(snapshot or {}),
        "move_start_at": (
            start.isoformat().replace("+00:00", "Z") if start else None
        ),
        "latency_minutes": signed_latency,
        "snapshot_lead_minutes": lead_minutes,
        "rank": (ranked_match or (None,))[0],
        "execution_rank": (actionable_match or (None,))[0],
        "ranking_lane": (ranked_match or actionable_match or (None, None, None))[2],
        "candidate_direction": candidate_direction or None,
        "direction_correct": (
            candidate_direction == truth_direction
            if candidate_direction and truth_direction else None
        ),
        "stages": {
            "market_move": True,
            "discovered": discovered,
            "setup_confirmed": setup_confirmed,
            "execution_qualified": execution_qualified,
        },
        "fill_assumed": False,
    }


def _outcome_linkage(truth: dict[str, Any], radar_link: dict[str, Any]) -> dict[str, Any]:
    direction = _direction(truth.get("direction") or truth.get("label"))
    suffix = "long" if direction == "bullish" else "short" if direction == "bearish" else None
    return {
        "status": "retrospective_ground_truth_linked",
        "measurement_basis": "ground_truth_horizon_from_trigger_no_fill_assumed",
        "mfe": _number(truth.get(f"peak_favorable_{suffix}")) if suffix else None,
        "mae": _number(truth.get(f"peak_adverse_{suffix}")) if suffix else None,
        "max_achievable_r": _number(truth.get(f"achievable_r_{suffix}")) if suffix else None,
        "realized_r_at_horizon": _number(truth.get(f"realized_r_{suffix}")) if suffix else None,
        "direction_correct": radar_link.get("direction_correct"),
        "rank": radar_link.get("rank"),
        "execution_rank": radar_link.get("execution_rank"),
        "latency_minutes": radar_link.get("latency_minutes"),
        "snapshot_lead_minutes": radar_link.get("snapshot_lead_minutes"),
        "fill_assumed": False,
    }


def _cluster_move_windows(moves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse overlapping same-direction labels into distinct move windows."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in moves:
        if row.get("excluded") is True or row.get("metrics_qualified") is False:
            continue
        symbol = _symbol(row)
        if symbol:
            grouped.setdefault(symbol, []).append(row)

    windows: list[dict[str, Any]] = []
    for symbol, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: _move_start(row) or datetime.max.replace(tzinfo=timezone.utc))
        cluster: list[dict[str, Any]] = []
        cluster_end: datetime | None = None

        def flush() -> None:
            nonlocal cluster, cluster_end
            if not cluster:
                return
            first = cluster[0]
            link = dict(first.get("radar_linkage") or {})
            outcomes = [row.get("outcome_linkage") or {} for row in cluster]
            start = _move_start(first)
            end_values = [_dt(row.get("horizon_end_ts")) for row in cluster]
            end_values = [value for value in end_values if value]
            timeframes = sorted({str(row.get("timeframe") or "unknown") for row in cluster})
            stages = {
                stage: bool(link.get("stages", {}).get(stage))
                for stage in STAGE_DEFINITIONS
            }
            stages["market_move"] = True
            windows.append({
                "window_id": f"{symbol}:{_direction(first.get('direction') or first.get('label'))}:{start.isoformat() if start else len(windows)}",
                "symbol": symbol,
                "timeframe": str(first.get("timeframe") or "unknown"),
                "timeframes": timeframes,
                "direction": _direction(first.get("direction") or first.get("label")),
                "move_start_at": start.isoformat().replace("+00:00", "Z") if start else None,
                "window_end_at": max(end_values).isoformat().replace("+00:00", "Z") if end_values else None,
                "constituent_move_ids": [row.get("move_id") for row in cluster],
                "label_count": len(cluster),
                "stages": stages,
                "radar_linkage": link,
                "outcome_linkage": {
                    "status": "clustered_retrospective_ground_truth",
                    "measurement_basis": "maximum_across_overlapping_labels_no_fill_assumed",
                    "mfe": max((value for value in (_number(row.get("mfe")) for row in outcomes) if value is not None), default=None),
                    "mae": max((value for value in (_number(row.get("mae")) for row in outcomes) if value is not None), default=None),
                    "max_achievable_r": max((value for value in (_number(row.get("max_achievable_r")) for row in outcomes) if value is not None), default=None),
                    "direction_correct": link.get("direction_correct"),
                    "rank": link.get("rank"),
                    "latency_minutes": link.get("latency_minutes"),
                    "fill_assumed": False,
                },
            })
            cluster = []
            cluster_end = None

        for row in rows:
            start = _move_start(row)
            end = _dt(row.get("horizon_end_ts")) or start
            direction = _direction(row.get("direction") or row.get("label"))
            current_direction = _direction(cluster[0].get("direction") or cluster[0].get("label")) if cluster else None
            if cluster and (direction != current_direction or not start or not cluster_end or start > cluster_end):
                flush()
            cluster.append(row)
            if end and (cluster_end is None or end > cluster_end):
                cluster_end = end
        flush()
    return sorted(windows, key=lambda row: (str(row.get("move_start_at") or ""), str(row.get("symbol") or "")))


def _market_coverage(ground_truth: dict[str, Any]) -> dict[str, Any]:
    pairs = [row for row in ground_truth.get("pair_status") or [] if isinstance(row, dict)]
    unavailable = [
        {
            "instrument": _symbol(row),
            "timeframe": row.get("timeframe"),
            "reason": row.get("reason") or "coverage_unqualified",
        }
        for row in pairs if not row.get("qualified")
    ]
    qualified = [row for row in pairs if row.get("qualified")]
    qualified_instruments = {_symbol(row) for row in qualified if _symbol(row)}
    unavailable_instrument_set = {_symbol(row) for row in unavailable if _symbol(row)}
    status = (
        "legacy_unspecified"
        if not pairs
        else "complete"
        if not unavailable
        else "partial"
        if qualified
        else "unavailable"
    )
    return {
        "status": status,
        "qualified_pair_count": len(qualified),
        "unavailable_pair_count": len(unavailable),
        "unavailable_pairs": unavailable,
        "unavailable_instruments": sorted(unavailable_instrument_set - qualified_instruments),
        "partially_unavailable_instruments": sorted(unavailable_instrument_set & qualified_instruments),
        "no_move_interpretation_allowed": bool(pairs) and not unavailable,
        "message": (
            "Missing coverage is unknown, not evidence that no market move occurred."
            if unavailable
            else "Coverage metadata is absent; zero labels cannot establish that no move occurred."
            if not pairs
            else "All requested instrument/timeframe pairs were covered."
        ),
    }


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


def _outcome_r(row: dict[str, Any]) -> float | None:
    value: Any = row.get("outcome_r")
    if value is None:
        value = row.get("realized_r")
    if value is None:
        for key in ("outcome_eod", "outcome_60m", "outcome_15m", "outcome_5m", "outcome"):
            nested = row.get(key)
            if isinstance(nested, dict):
                value = nested.get("outcome_r")
                if value is None:
                    value = nested.get("realized_r")
                if value is not None:
                    break
    return _number(value)


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
    outcome_rows: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Measure price-move coverage and pattern annotations without conflating them."""
    family_map = families or _taxonomy_families()
    date_key = str(ground_truth.get("date") or "")[:10]

    def event_key(row: dict[str, Any], pattern_id: str, row_date: str) -> tuple[str, str, str, str, str, str]:
        stamp = _dt(row.get("trigger_bar_ts") or row.get("bar_close_ts"))
        trigger = stamp.isoformat().replace("+00:00", "Z") if stamp else ""
        direction = str(row.get("direction") or "").lower()
        if direction in {"long", "bull"}:
            direction = "bullish"
        elif direction in {"short", "bear"}:
            direction = "bearish"
        timeframe = str(row.get("timeframe") or row.get("trigger_timeframe") or "").lower()
        return (
            row_date,
            str(row.get("symbol") or row.get("instrument") or "").upper(),
            pattern_id,
            timeframe,
            trigger,
            direction,
        )

    truth: set[tuple[str, str, str, str, str, str]] = set()
    truth_family: dict[tuple[str, str, str, str, str, str], str] = {}
    for move in ground_truth.get("moves") or []:
        if not isinstance(move, dict):
            continue
        for pattern_id, family in _pattern_labels(move, family_map):
            key = event_key(move, pattern_id, date_key)
            truth.add(key)
            truth_family[key] = family

    detections: set[tuple[str, str, str, str, str, str]] = set()
    detection_family: dict[tuple[str, str, str, str, str, str], str] = {}
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
        key = event_key(row, pattern_id, row_date)
        detections.add(key)
        detection_family[key] = _pattern_family(row, family_map)
        usable_rows.append(row)

    latest_outcomes: dict[str, dict[str, Any]] = {}
    for outcome in outcome_rows:
        if not isinstance(outcome, dict):
            continue
        detection_id = str(outcome.get("detection_id") or outcome.get("event_id") or outcome.get("candidate_id") or "")
        if detection_id:
            latest_outcomes[detection_id] = {**latest_outcomes.get(detection_id, {}), **outcome}

    resolved_rows: list[dict[str, Any]] = []
    for row in usable_rows:
        detection_id = str(row.get("detection_id") or row.get("event_id") or row.get("candidate_id") or "")
        merged = {**row, **latest_outcomes.get(detection_id, {})}
        if _outcome(merged) is not None:
            resolved_rows.append(merged)

    move_metrics_qualified = bool(ground_truth.get("metrics_qualified"))
    pattern_metrics_qualified = move_metrics_qualified and bool(
        ground_truth.get("pattern_annotation_qualified")
    )

    def outcome_quality(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        resolved = [row for row in rows if _outcome(row) is not None]
        outcomes = [_outcome(row) for row in resolved]
        realized = [_outcome_r(row) for row in resolved]
        realized = [value for value in realized if value is not None]
        return {
            "resolved_outcomes": len(resolved),
            "wins": sum(value == 1.0 for value in outcomes),
            "observed_win_rate": round(sum(value == 1.0 for value in outcomes) / len(outcomes), 4) if outcomes else None,
            "average_r": round(sum(realized) / len(realized), 4) if realized else None,
        }

    pattern_ids = sorted({key[2] for key in truth | detections})
    per_pattern: list[dict[str, Any]] = []
    for pattern_id in pattern_ids:
        pattern_truth = {key for key in truth if key[2] == pattern_id}
        pattern_detected = {key for key in detections if key[2] == pattern_id}
        hits = pattern_truth & pattern_detected
        pattern_outcomes = [row for row in resolved_rows if _pattern_id(row) == pattern_id]
        per_pattern.append({
            "pattern_id": pattern_id,
            "family": family_map.get(pattern_id) or next((detection_family[key] for key in pattern_detected), "unclassified"),
            "ground_truth_labeled": len(pattern_truth),
            "grader_detected": len(pattern_detected),
            "true_positives": len(hits),
            "false_positives": len(pattern_detected - pattern_truth),
            "false_negatives": len(pattern_truth - pattern_detected),
            "precision": round(len(hits) / len(pattern_detected), 4) if pattern_metrics_qualified and pattern_detected else None,
            "recall": round(len(hits) / len(pattern_truth), 4) if pattern_metrics_qualified and pattern_truth else None,
            "coverage_delta": round((len(pattern_detected) - len(pattern_truth)) / len(pattern_truth), 4) if pattern_metrics_qualified and pattern_truth else None,
            "outcome_quality": outcome_quality(pattern_outcomes),
        })

    per_family: list[dict[str, Any]] = []
    for family in sorted({row["family"] for row in per_pattern}):
        rows = [row for row in per_pattern if row["family"] == family]
        labeled = sum(row["ground_truth_labeled"] for row in rows)
        detected = sum(row["grader_detected"] for row in rows)
        hits = sum(row["true_positives"] for row in rows)
        family_outcomes = [row for row in resolved_rows if _pattern_family(row, family_map) == family]
        per_family.append({
            "family": family,
            "ground_truth_labeled": labeled,
            "grader_detected": detected,
            "true_positives": hits,
            "false_positives": sum(row["false_positives"] for row in rows),
            "false_negatives": sum(row["false_negatives"] for row in rows),
            "precision": round(hits / detected, 4) if pattern_metrics_qualified and detected else None,
            "recall": round(hits / labeled, 4) if pattern_metrics_qualified and labeled else None,
            "coverage_delta": round((detected - labeled) / labeled, 4) if pattern_metrics_qualified and labeled else None,
            "outcome_quality": outcome_quality(family_outcomes),
        })

    cisd_rows = []
    for row in usable_rows:
        if _pattern_id(row) != "ict_cisd_universal_model":
            continue
        detection_id = str(row.get("detection_id") or row.get("event_id") or row.get("candidate_id") or "")
        cisd_rows.append({**row, **latest_outcomes.get(detection_id, {})})
    resolved = [row for row in cisd_rows if _outcome(row) is not None]
    scored = [(_probability(row), _outcome(row)) for row in resolved]
    scored = [(probability, outcome) for probability, outcome in scored if probability is not None and outcome is not None]

    def opportunity_key(row: dict[str, Any], row_date: str) -> tuple[str, str, str, str, str]:
        _, symbol, _, timeframe, trigger, direction = event_key(row, "", row_date)
        label = row.get("label")
        if not direction and label in {1, "+1"}:
            direction = "bullish"
        elif not direction and label in {-1, "-1"}:
            direction = "bearish"
        return row_date, symbol, timeframe, trigger, direction

    move_truth = {
        opportunity_key(row, date_key)
        for row in ground_truth.get("moves") or []
        if isinstance(row, dict)
        and row.get("excluded") is not True
        and row.get("label") in {1, -1, "+1", "-1"}
    }
    detected_events = {opportunity_key(row, _row_date(row)) for row in usable_rows}
    opportunity_hits = move_truth & detected_events
    opportunity_coverage = {
        "metrics_qualified": move_metrics_qualified,
        "ground_truth_moves": len(move_truth),
        "detected_events": len(detected_events),
        "true_positives": len(opportunity_hits),
        "false_positives": len(detected_events - move_truth),
        "false_negatives": len(move_truth - detected_events),
        "precision": round(len(opportunity_hits) / len(detected_events), 4) if move_metrics_qualified and detected_events else None,
        "recall": round(len(opportunity_hits) / len(move_truth), 4) if move_metrics_qualified and move_truth else None,
        "coverage_delta": round((len(detected_events) - len(move_truth)) / len(move_truth), 4) if move_metrics_qualified and move_truth else None,
    }
    status = (
        "unqualified_move_denominator"
        if not move_metrics_qualified
        else "measured"
        if pattern_metrics_qualified
        else "opportunity_measured_pattern_annotation_missing"
    )
    return {
        "status": status,
        "metrics_qualified": move_metrics_qualified,
        "pattern_metrics_qualified": pattern_metrics_qualified,
        "source_labels": ["data/pattern_grader_log.jsonl", "move_universe_ground_truth"],
        "totals": {
            "ground_truth_labeled": len(truth),
            "grader_detected": len(detections),
            "true_positives": len(truth & detections),
            "coverage_delta": round((len(detections) - len(truth)) / len(truth), 4) if pattern_metrics_qualified and truth else None,
        },
        "opportunity_coverage": opportunity_coverage,
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
    pattern_outcome_rows: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    date_key = str(ground_truth.get("date") or "")[:10]
    snapshots = sorted(
        (row for row in radar_history if str(row.get("date") or "")[:10] == date_key),
        key=lambda row: _stamp(row) or "",
    )
    first_discovered: dict[str, str] = {}
    first_discovery_ranked: dict[str, dict[str, Any]] = {}
    first_ranked: dict[str, dict[str, Any]] = {}
    final_top_k: list[str] = []
    final_discovery_top_k: list[str] = []
    uses_actionable_ranking = any(
        "actionable_ranked_candidates" in snapshot
        or "actionable_ranked_candidates" in (snapshot.get("benchmark_lane") or {})
        for snapshot in snapshots
    )
    for snapshot in snapshots:
        stamp = _stamp(snapshot)
        for symbol in snapshot.get("all_discovered_symbols") or []:
            if stamp:
                first_discovered.setdefault(str(symbol).upper(), stamp)
        discovery_entries = _lane_ranked_entries(snapshot, "ranked_candidates")
        ranked_entries = (
            _lane_ranked_entries(snapshot, "actionable_ranked_candidates")
            if uses_actionable_ranking else discovery_entries
        )
        final_discovery_top_k = [
            _symbol(row) for rank, row, _lane in discovery_entries if rank <= k
        ]
        final_top_k = [_symbol(row) for rank, row, _lane in ranked_entries if rank <= k]
        for rank, candidate, lane in discovery_entries:
            symbol = str(candidate["symbol"]).upper()
            if stamp and symbol not in first_discovery_ranked:
                first_discovery_ranked[symbol] = {"timestamp": stamp, "rank": rank, "candidate": candidate, "lane": lane}
        for rank, candidate, lane in ranked_entries:
            symbol = str(candidate["symbol"]).upper()
            if stamp and symbol not in first_ranked:
                first_ranked[symbol] = {"timestamp": stamp, "rank": rank, "candidate": candidate, "lane": lane}

    moves: list[dict[str, Any]] = []
    for truth in ground_truth.get("moves") or []:
        if (
            not isinstance(truth, dict)
            or truth.get("excluded") is True
            or truth.get("metrics_qualified") is False
        ):
            continue
        symbol = str(truth.get("symbol") or "").upper()
        ranked = first_ranked.get(symbol)
        discovery_ranked = first_discovery_ranked.get(symbol)
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
        radar_linkage = _nearest_prior_link(truth, snapshots)
        linked_rank = radar_linkage.get("rank")
        linked_execution_rank = radar_linkage.get("execution_rank")
        effective_rank = linked_execution_rank if uses_actionable_ranking else linked_rank
        linked_stages = radar_linkage.get("stages") or {}
        if radar_linkage.get("status") in {"no_prior_snapshot", "stale_prior_snapshot"}:
            partition = "scanner_coverage_gap"
        elif not linked_stages.get("discovered"):
            partition = "discovery_miss"
        elif effective_rank is None or int(effective_rank) > k:
            partition = "ranking_miss"
        elif radar_linkage.get("direction_correct") is False:
            partition = "false_positive"
        elif not linked_stages.get("setup_confirmed"):
            partition = "confirmation_miss"
        elif uses_actionable_ranking and (
            linked_execution_rank is None or int(linked_execution_rank) > k
        ):
            partition = "execution_gate_miss"
        else:
            partition = "correct_entry"
        outcome_linkage = _outcome_linkage(truth, radar_linkage)
        moves.append({
            **truth,
            "first_discovered_at": discovered_at,
            "first_ranked_at": (ranked or {}).get("timestamp"),
            "first_rank": (ranked or {}).get("rank"),
            "first_actionable_rank": (ranked or {}).get("rank") if uses_actionable_ranking else None,
            "first_discovery_ranked_at": (discovery_ranked or {}).get("timestamp"),
            "first_discovery_rank": (discovery_ranked or {}).get("rank"),
            "ranking_lane": (discovery_ranked or ranked or {}).get("lane", "legacy_global"),
            "discovery_latency_bars": latency_bars,
            "stages": radar_linkage["stages"],
            "radar_linkage": radar_linkage,
            "outcome_linkage": outcome_linkage,
            "partition": partition,
            "regime": regime,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    move_windows = _cluster_move_windows(moves)
    stage_counts = {
        "market_moves": len(move_windows),
        "discovered": sum(bool(row["stages"]["discovered"]) for row in move_windows),
        "setup_confirmed": sum(bool(row["stages"]["setup_confirmed"]) for row in move_windows),
        "execution_qualified": sum(bool(row["stages"]["execution_qualified"]) for row in move_windows),
    }
    actionable_window_ranks = [
        row["radar_linkage"].get("execution_rank")
        if uses_actionable_ranking
        else row["radar_linkage"].get("rank")
        for row in move_windows
    ]
    actionable_recalled_windows = [
        row
        for row, rank in zip(move_windows, actionable_window_ranks)
        if rank is not None and int(rank) <= k
    ]
    discovery_recalled_windows = [
        row
        for row in move_windows
        if row["radar_linkage"].get("rank") is not None
        and int(row["radar_linkage"]["rank"]) <= k
    ]
    actionable_direction_hits = [
        row for row in actionable_recalled_windows
        if row["radar_linkage"].get("direction_correct") is True
    ]
    discovery_direction_hits = [
        row for row in discovery_recalled_windows
        if row["radar_linkage"].get("direction_correct") is True
    ]
    latencies = [int(row["discovery_latency_bars"]) for row in moves if row.get("discovery_latency_bars") is not None]
    counts: dict[str, int] = {}
    for row in moves:
        counts[str(row["partition"])] = counts.get(str(row["partition"]), 0) + 1
    metrics = {
        "k": k,
        "ground_truth_count": len(move_windows),
        "ground_truth_label_count": len(moves),
        "market_move_window_count": len(move_windows),
        "recall_at_k": round(len(actionable_recalled_windows) / len(move_windows), 4) if move_windows else None,
        "precision_at_k": round(len(actionable_direction_hits) / len(actionable_recalled_windows), 4) if actionable_recalled_windows else None,
        "precision_basis": "causal_directional_precision_among_move_windows_ranked_at_or_before_move_start",
        "ranking_source": "actionable_ranked_candidates" if uses_actionable_ranking else "ranked_candidates_legacy",
        "discovery_recall_at_k": round(len(discovery_recalled_windows) / len(move_windows), 4) if move_windows else None,
        "discovery_precision_at_k": round(len(discovery_direction_hits) / len(discovery_recalled_windows), 4) if discovery_recalled_windows else None,
        "median_discovery_latency_bars": sorted(latencies)[len(latencies) // 2] if latencies else None,
        "partition_counts": counts,
        "snapshots_reviewed": len(snapshots),
    }
    pattern_coverage = build_pattern_coverage(
        ground_truth,
        pattern_grader_rows,
        outcome_rows=pattern_outcome_rows,
    )
    market_coverage = _market_coverage(ground_truth)
    warnings = ["Recall and precision measure detection, not profitability or executable edge."]
    if market_coverage["status"] != "complete":
        warnings.append(
            "One or more requested market-data pairs were unavailable; absence of labeled moves for those pairs must not be interpreted as no move."
        )
    warnings.append("Negative outcome-linkage latency means the linked radar snapshot preceded the move; no fill is assumed.")
    return {
        "schema_version": 2,
        "provider": "detection_scorecard",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": date_key,
        "metrics": metrics,
        "summary": {
            "stage_counts": stage_counts,
            "stage_denominator": "distinct_overlapping_ground_truth_move_windows",
        },
        "stage_definitions": STAGE_DEFINITIONS,
        "market_coverage": market_coverage,
        "ground_truth_status": ground_truth.get("ground_truth_status", "legacy_unspecified"),
        "metrics_qualified": bool(ground_truth.get("metrics_qualified", True)),
        "pattern_coverage": pattern_coverage,
        "per_regime": {regime: metrics},
        "latency_histogram": [{"bars": value, "count": latencies.count(value)} for value in sorted(set(latencies))],
        "moves": moves,
        "move_windows": move_windows,
        "missed_moves": [row for row in moves if row["partition"] != "correct_entry"],
        "warnings": warnings,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_rolling(reports: Iterable[dict[str, Any]], *, window: int = 30) -> dict[str, Any]:
    rows = sorted((row for row in reports if row.get("metrics")), key=lambda row: str(row.get("date") or ""))[-window:]
    truth = sum(int(row["metrics"].get("market_move_window_count") or row["metrics"].get("ground_truth_count") or 0) for row in rows)
    recalled = sum(
        sum(
            1
            for move in row.get("move_windows") or row.get("moves") or []
            if (move.get("radar_linkage") or {}).get("execution_rank") is not None
            and int((move.get("radar_linkage") or {})["execution_rank"]) <= int(row["metrics"].get("k") or 10)
        )
        for row in rows
    )
    # Legacy reports did not persist execution_rank; use their already-frozen
    # daily numerator rather than reinterpreting label rows as move windows.
    recalled += sum(
        round(float(row["metrics"]["recall_at_k"]) * int(row["metrics"].get("market_move_window_count") or row["metrics"].get("ground_truth_count") or 0))
        for row in rows
        if not any((move.get("radar_linkage") or {}).get("execution_rank") is not None for move in row.get("move_windows") or [])
        and row["metrics"].get("recall_at_k") is not None
    )
    discovery_recalled = sum(
        sum(
            1
            for move in row.get("move_windows") or row.get("moves") or []
            if (move.get("radar_linkage") or {}).get("rank") is not None
            and int((move.get("radar_linkage") or {})["rank"]) <= int(row["metrics"].get("k") or 10)
        )
        for row in rows
    )
    final_precision_values = [float(row["metrics"]["precision_at_k"]) for row in rows if row["metrics"].get("precision_at_k") is not None]
    discovery_precision_values = [
        float(row["metrics"]["discovery_precision_at_k"])
        for row in rows
        if row["metrics"].get("discovery_precision_at_k") is not None
    ]
    missed = [move for row in rows for move in row.get("missed_moves") or []]
    latest_pattern = rows[-1].get("pattern_coverage", {}) if rows else {}
    staged_rows = [row for row in rows if isinstance(row.get("summary", {}).get("stage_counts"), dict)]
    stage_counts = {
        key: sum(int(row["summary"]["stage_counts"].get(key) or 0) for row in staged_rows)
        for key in ("market_moves", "discovered", "setup_confirmed", "execution_qualified")
    }
    latest = rows[-1] if rows else {}
    latest_metrics = latest.get("metrics", {}) if isinstance(latest.get("metrics"), dict) else {}
    latest_stage_counts = (
        latest.get("summary", {}).get("stage_counts", {})
        if isinstance(latest.get("summary"), dict)
        else {}
    )
    return {
        "schema_version": 2,
        "provider": "detection_scorecard_rolling",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sessions": len(rows),
        "summary": {
            "stage_counts": stage_counts,
            "stage_denominator": "distinct_overlapping_ground_truth_move_windows",
            "staged_sessions": len(staged_rows),
            "legacy_unstaged_sessions": len(rows) - len(staged_rows),
        },
        "stage_definitions": STAGE_DEFINITIONS,
        "latest_session": {
            "date": latest.get("date"),
            "stage_counts": latest_stage_counts,
            "market_coverage": latest.get("market_coverage", {}),
            "ground_truth_count": latest_metrics.get("ground_truth_count"),
            "market_move_window_count": latest_metrics.get("market_move_window_count"),
        } if latest else {},
        "metrics": {
            "recall_at_10": round(recalled / truth, 4) if truth else None,
            "precision_at_10_mean": round(sum(final_precision_values) / len(final_precision_values), 4) if final_precision_values else None,
            "actionable_recall_at_10": round(recalled / truth, 4) if truth else None,
            "actionable_precision_at_10_mean": round(sum(final_precision_values) / len(final_precision_values), 4) if final_precision_values else None,
            "discovery_recall_at_10": round(discovery_recalled / truth, 4) if truth else None,
            "discovery_precision_at_10_mean": round(sum(discovery_precision_values) / len(discovery_precision_values), 4) if discovery_precision_values else None,
            "ground_truth_count": truth,
            "root_cause_coverage": round(sum(bool(move.get("partition")) for move in missed) / len(missed), 4) if missed else None,
        },
        "top_missed_moves": sorted(missed, key=lambda row: abs(float(row.get("move_pct") or 0.0)), reverse=True)[:10],
        "daily": [{"date": row.get("date"), **row.get("metrics", {})} for row in rows],
        "pattern_coverage": latest_pattern,
        "market_coverage": latest.get("market_coverage", {}) if latest else {},
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
    parser.add_argument("--pattern-grader-outcomes", type=Path, default=PATTERN_GRADER_OUTCOMES)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    compact = args.date.replace("-", "")
    ground = _read_json(args.data_dir / f"move_ground_truth_{compact}.json")
    report = build_scorecard(
        ground,
        _read_jsonl(args.radar_log),
        k=args.k,
        pattern_grader_rows=_read_jsonl(args.pattern_grader_log),
        pattern_outcome_rows=_read_jsonl(args.pattern_grader_outcomes),
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
