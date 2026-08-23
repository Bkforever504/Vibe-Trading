#!/usr/bin/env python3
"""Project completed-bar market-structure decisions into one evidence spine.

The scanner reads the live opportunity report, creates stable causal detection
envelopes, and appends only new snapshots. It has no broker or order authority.
Grades remain setup-quality labels; probability is unavailable until a matching
forward-calibration bucket qualifies independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
SOURCE_REPORT = REPORT_DIR / "live-opportunity-engine.json"
LEDGER_PATH = ROOT / "data" / "pattern_grader_log.jsonl"
REPORT_PATH = REPORT_DIR / "pattern-grader-grades.json"
EVIDENCE_SPEC = ROOT / "research" / "APLUS_ENTRY_EXIT_TIMEFRAME_EVIDENCE_SPEC_2026-08-22.md"
TIMEFRAME_POLICY = ROOT / "research" / "aplus_timeframe_matrix.json"

ENVELOPE_VERSION = 1
DETECTOR_VERSION = "market_structure_intelligence_v5"
PLAN_VERSION = "manual_pattern_plan_v1"
ASSET_TIMEFRAME_POLICY_ID = "us_cash_equity_aplus_v1"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(prefix: str, value: Any, *, length: int = 24) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:length]}"


def _file_hash(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(payload).hexdigest()


def _feed_quality(
    snapshot: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    decision_at: str,
    now: datetime,
) -> dict[str, Any]:
    feed = _dict(snapshot.get("feed"))
    quote = _dict(row.get("quote"))
    feed_name = str(feed.get("feed") or "unknown").lower()
    source_event = _timestamp(quote.get("timestamp") or feed.get("last_event_at"))
    event_dt = None
    if source_event:
        event_dt = datetime.fromisoformat(source_event.replace("Z", "+00:00"))
    age_ms = max(0.0, (now - event_dt).total_seconds() * 1000.0) if event_dt else None
    bid = _number(quote.get("bid"))
    ask = _number(quote.get("ask"))
    crossed = bid is not None and ask is not None and bid > ask
    freshness = str(row.get("freshness") or quote.get("freshness") or "missing")
    blockers: list[str] = []
    if freshness not in {"live", "recent"}:
        blockers.append("stale_or_missing_quote")
    if crossed:
        blockers.append("crossed_quote")
    if feed_name == "iex":
        venue_coverage = "iex_single_venue_not_consolidated_sip"
    elif feed_name == "sip":
        venue_coverage = "sip_consolidated_us_equities"
    else:
        venue_coverage = "unknown"
        blockers.append("feed_coverage_unknown")
    return {
        "provider": str(feed.get("provider") or "alpaca"),
        "feed": feed_name,
        "label": str(feed.get("label") or f"alpaca_{feed_name}"),
        "entitlement_status": str(feed.get("entitlement_status") or "configured_not_verified"),
        "venue_coverage": venue_coverage,
        "source_event_time": source_event,
        "received_at": decision_at,
        "decision_at": decision_at,
        "age_ms": round(age_ms, 1) if age_ms is not None else None,
        "transport_latency_ms": None,
        "clock_skew_ms": None,
        "delayed": freshness not in {"live", "recent"},
        "sequence_gap_count": None,
        "crossed_or_invalid_quote": crossed or bid is None or ask is None,
        "session": "US_EQUITY_RTH_OR_EXTENDED_AS_LABELED_BY_SOURCE",
        "completed_bar_cut": _timestamp(row.get("bar_completed_at")),
        "last_good_at": source_event if not blockers else None,
        "freshness_threshold_ms": 15_000,
        "quality_status": "qualified_for_review" if not blockers else "blocked",
        "blockers": blockers,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _row_envelope(
    snapshot: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    now: datetime,
    watch: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    watch = dict(watch or {})
    structure = _dict(row.get("market_structure")) or watch
    best = _dict(structure.get("best_setup")) or _dict(watch.get("best_setup"))
    pattern_grade = _dict(structure.get("pattern_grade")) or _dict(row.get("pattern_grade")) or _dict(watch.get("pattern_grade"))
    if not structure or str(pattern_grade.get("rubric_version") or "") != "pattern_grade_v1":
        return None
    pattern_id = str(best.get("pattern_id") or row.get("setup_family") or "").strip()
    symbol = str(row.get("symbol") or watch.get("symbol") or "").upper().strip()
    direction = str(row.get("direction") or best.get("direction") or "neutral").lower()
    if not symbol or not pattern_id or direction not in {"bullish", "bearish", "long", "short"}:
        return None

    entry_plan = _dict(structure.get("entry_plan")) or _dict(watch.get("entry_plan"))
    exit_plan = _dict(structure.get("exit_plan")) or _dict(watch.get("exit_plan"))
    timeframe_coverage = _dict(structure.get("timeframe_coverage")) or _dict(watch.get("timeframe_coverage"))
    timeframe_alignment = _dict(structure.get("timeframe_alignment")) or _dict(watch.get("timeframe_alignment"))
    trigger = _number(best.get("trigger"))
    if trigger is None:
        trigger = _number(row.get("entry") if row.get("entry") is not None else entry_plan.get("trigger"))
    invalidation = _number(best.get("invalidation"))
    if invalidation is None:
        invalidation = _number(row.get("invalidation") if row.get("invalidation") is not None else entry_plan.get("invalidation"))
    trigger_bar_ts = _timestamp(
        row.get("bar_completed_at")
        or best.get("trigger_bar_ts")
        or best.get("timestamp")
        or snapshot.get("generated_at")
    )
    if trigger_bar_ts is None:
        return None
    decision_at = _timestamp(snapshot.get("generated_at")) or now.isoformat().replace("+00:00", "Z")
    canonical_direction = "bullish" if direction in {"bullish", "long"} else "bearish"
    entry_zone = _dict(entry_plan.get("entry_zone"))
    targets = [dict(item) for item in _list(row.get("targets") or exit_plan.get("targets")) if isinstance(item, dict)]
    immutable_plan = {
        "plan_version": PLAN_VERSION,
        "trigger": trigger,
        "entry_zone": {
            "low": _number(entry_zone.get("low")) if entry_zone else trigger,
            "high": _number(entry_zone.get("high")) if entry_zone else trigger,
        },
        "maximum_chase": _number(entry_plan.get("maximum_chase")),
        "invalidation": invalidation,
        "targets": targets,
        "time_stop_bars": exit_plan.get("time_stop_bars"),
        "order_style": "manual_review_after_completed_bar_and_fresh_quote_revalidation",
        "post_friction_reward_risk": _number(row.get("reward_risk_after_friction")),
        "data_cut": trigger_bar_ts,
        "no_trade_conditions": sorted({str(item) for item in _list(row.get("blockers") or watch.get("hard_blockers"))}),
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    plan_hash = _hash("plan", immutable_plan)
    lifecycle_key = {
        "asset_class": str(row.get("asset_class") or "equity"),
        "symbol": symbol,
        "pattern_id": pattern_id,
        "direction": canonical_direction,
        "causal_level": trigger,
        "trigger_bar_ts": trigger_bar_ts,
        "trigger_timeframe": "5m",
        "detector_version": DETECTOR_VERSION,
        "plan_version": PLAN_VERSION,
    }
    lifecycle_id = _hash("pd", lifecycle_key)
    grade = str(row.get("grade") or watch.get("grade") or pattern_grade.get("grade") or "D").upper()
    score = _number(row.get("decision_score"))
    if score is None:
        score = _number(watch.get("score") if watch.get("score") is not None else pattern_grade.get("final_score"))
    blockers = sorted({
        *(str(item) for item in _list(row.get("blockers"))),
        *(str(item) for item in _list(watch.get("hard_blockers"))),
        *(str(item) for item in _list(structure.get("hard_blockers"))),
    })
    feed_quality = _feed_quality(snapshot, row, decision_at=decision_at, now=now)
    source_labels = list(dict.fromkeys([
        *(str(item) for item in _list(row.get("source_labels"))),
        *(str(item) for item in _list(watch.get("source_labels"))),
        "pattern_detection_envelope_v1",
    ]))
    envelope: dict[str, Any] = {
        "schema_version": ENVELOPE_VERSION,
        "detection_id": lifecycle_id,
        "lifecycle_id": lifecycle_id,
        "event_type": "pattern_detection_snapshot",
        "date": trigger_bar_ts[:10],
        "observed_at": decision_at,
        "trigger_bar_ts": trigger_bar_ts,
        "bar_close_ts": trigger_bar_ts,
        "asset_class": str(row.get("asset_class") or "equity"),
        "symbol": symbol,
        "instrument": symbol,
        "pattern_id": pattern_id,
        "setup_family": pattern_id,
        "pattern_family": str(best.get("family") or "unknown"),
        "regime": str(structure.get("structure_regime") or watch.get("structure_regime") or "unavailable"),
        "direction": canonical_direction,
        "trigger_timeframe": "5m",
        "asset_timeframe_policy_id": ASSET_TIMEFRAME_POLICY_ID,
        "detector_version": DETECTOR_VERSION,
        "spec_version": "2026-08-22",
        "spec_hash": _file_hash(EVIDENCE_SPEC),
        "timeframe_policy_hash": _file_hash(TIMEFRAME_POLICY),
        "producer_aliases": [str(row.get("candidate_id"))] if row.get("candidate_id") else [],
        "trigger_state": str(best.get("trigger_state") or "observed"),
        "state": str(row.get("state") or watch.get("decision") or "WATCH"),
        "grade": grade,
        "score": score,
        "pattern_grade": pattern_grade,
        "probability": {
            "value": None,
            "status": "not_calibrated",
            "label": "No qualified forward-calibrated probability",
            "ranking_eligible": False,
        },
        "trigger": trigger,
        "entry": trigger,
        "invalidation": invalidation,
        "targets": targets,
        "geometry_complete": trigger is not None and invalidation is not None and trigger != invalidation,
        "plan_hash": plan_hash,
        "immutable_plan": immutable_plan,
        "blockers": blockers,
        "timeframe_coverage": timeframe_coverage,
        "timeframe_alignment": timeframe_alignment,
        "feed_quality": feed_quality,
        "freshness": str(row.get("freshness") or watch.get("freshness") or "missing"),
        "source_labels": source_labels,
        "source_report": "~/.vibe-trading/reports/live-opportunity-engine.json",
        "outcome_5m": None,
        "outcome_15m": None,
        "outcome_60m": None,
        "outcome_eod": None,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    fingerprint = {key: value for key, value in envelope.items() if key not in {"observed_at", "snapshot_id"}}
    envelope["snapshot_id"] = _hash("snapshot", fingerprint)
    return envelope


def project_snapshot(
    snapshot: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Return stable detections plus a reconciled per-symbol scan denominator."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    watch_rows = [dict(item) for item in _list(snapshot.get("market_structure_watchlist")) if isinstance(item, dict)]
    watch_by_symbol = {str(item.get("symbol") or "").upper(): item for item in watch_rows if item.get("symbol")}
    detections: list[dict[str, Any]] = []
    emitted_keys: set[tuple[str, str, str]] = set()
    emitted_symbols: set[str] = set()
    for candidate in _list(snapshot.get("candidates")):
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "").upper()
        envelope = _row_envelope(snapshot, candidate, now=now, watch=watch_by_symbol.get(symbol))
        if envelope is None:
            continue
        key = (envelope["symbol"], envelope["pattern_id"], envelope["direction"])
        if key in emitted_keys:
            continue
        emitted_keys.add(key)
        emitted_symbols.add(envelope["symbol"])
        detections.append(envelope)
    for watch in watch_rows:
        envelope = _row_envelope(snapshot, {}, now=now, watch=watch)
        if envelope is None:
            continue
        key = (envelope["symbol"], envelope["pattern_id"], envelope["direction"])
        if key in emitted_keys:
            continue
        emitted_keys.add(key)
        emitted_symbols.add(envelope["symbol"])
        detections.append(envelope)
    detections.sort(key=lambda row: (str(row["trigger_bar_ts"]), row["symbol"], row["pattern_id"], row["direction"]))

    eligible_symbols = {str(row.get("symbol") or "").upper() for row in watch_rows if row.get("symbol")}
    blocked_symbols = {
        str(row.get("symbol") or "").upper()
        for row in watch_rows
        if row.get("symbol") and _list(row.get("hard_blockers"))
    }
    producer_failed = int(
        str(snapshot.get("stream_status") or "").lower() in {"reconnecting", "rest_polling_degraded", "failed"}
        or (not watch_rows and bool(snapshot))
    )
    reconciliation = {
        "eligible_symbol_count": len(eligible_symbols),
        "evaluated_symbol_count": len(watch_rows),
        "data_blocked_symbol_count": len(blocked_symbols),
        "emitted_detection_count": len(detections),
        "abstained_symbol_count": len(eligible_symbols - emitted_symbols),
        "producer_failure_count": producer_failed,
        "denominator_reconciled": len(eligible_symbols) == len(watch_rows),
    }
    return {
        "schema_version": 1,
        "provider": "pattern_grader_scanner",
        "generated_at": _timestamp(snapshot.get("generated_at")) or now.isoformat().replace("+00:00", "Z"),
        "source_report_schema_version": snapshot.get("schema_version"),
        "scan_reconciliation": reconciliation,
        "detections": detections,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


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
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def append_new_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    """Append snapshots not already present; keep multiple lifecycle updates."""
    values = [dict(row) for row in rows]
    existing_ids = {str(row.get("snapshot_id")) for row in _read_jsonl(path) if row.get("snapshot_id")}
    additions = [row for row in values if row.get("snapshot_id") and str(row["snapshot_id"]) not in existing_ids]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    if additions:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in additions:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return len(additions)


def build_pattern_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    scan_reconciliation: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    latest: dict[str, dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        detection_id = str(row.get("detection_id") or "")
        if not detection_id:
            continue
        prior = latest.get(detection_id)
        if prior is None or str(row.get("observed_at") or "") >= str(prior.get("observed_at") or ""):
            latest[detection_id] = row
    current = sorted(latest.values(), key=lambda row: (-float(_number(row.get("score")) or 0.0), str(row.get("symbol") or "")))
    grade_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for row in current:
        grade = str(row.get("grade") or "D").upper()
        family = str(row.get("pattern_id") or row.get("setup_family") or "unknown")
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1
    qualified = sum(bool(_dict(row.get("probability")).get("ranking_eligible")) for row in current)
    return {
        "schema_version": 1,
        "provider": "pattern_grader_report",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": "read_only_pattern_evidence",
        "summary": {
            "distinct_lifecycle_count": len(current),
            "a_grade_count": grade_counts.get("A", 0),
            "qualified_probability_count": qualified,
            "grade_counts": dict(sorted(grade_counts.items())),
            "family_counts": dict(sorted(family_counts.items())),
            "blocked_count": sum(bool(_list(row.get("blockers"))) for row in current),
        },
        "scan_reconciliation": dict(scan_reconciliation or {}),
        "latest_detections": current[:100],
        "warnings": [
            "Pattern grades are review-quality labels, not win probabilities.",
            "Only independently qualified forward calibration may populate probability fields.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_REPORT)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    source = _read_json(args.source)
    projected = project_snapshot(source)
    existing = _read_jsonl(args.ledger)
    appended = 0 if args.dry_run else append_new_rows(args.ledger, projected["detections"])
    report = build_pattern_report(
        [*existing, *projected["detections"]],
        scan_reconciliation=projected["scan_reconciliation"],
    )
    if not args.dry_run:
        _atomic_json(args.report, report)
    output = {
        "source_available": bool(source),
        "detections_projected": len(projected["detections"]),
        "snapshots_appended": appended,
        "scan_reconciliation": projected["scan_reconciliation"],
        "dry_run": args.dry_run,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    if args.print_output or args.dry_run:
        print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if source else 2


if __name__ == "__main__":
    raise SystemExit(main())
