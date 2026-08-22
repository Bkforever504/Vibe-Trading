#!/usr/bin/env python3
"""Enumerate and review every top-tier trade/setup observation each day.

Top tier means an explicit A+, a canonical Pattern Grade A where A is the
highest grade available, or a trade-like candidate with a score of at least
93. Repeated snapshots are retained as observation counts and grouped into one
setup lifecycle. This process is read-only with respect to brokers and cannot
submit orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
REPORT_PATH = REPORT_DIR / "daily-aplus-review.json"
LOG_PATH = DATA_DIR / "daily_aplus_review_log.jsonl"

DEFAULT_SOURCES: dict[str, Path] = {
    "pattern_grader": DATA_DIR / "pattern_grader_log.jsonl",
    "premarket_radar_log": DATA_DIR / "premarket_opportunity_radar_log.jsonl",
    "intraday_radar": DATA_DIR / "intraday_opportunity_radar_log.jsonl",
    "daily_edge_log": DATA_DIR / "daily_edge_orchestrator_log.jsonl",
    "premarket_radar": REPORT_DIR / "premarket-opportunity-radar.json",
    "intraday_radar_snapshot": REPORT_DIR / "intraday-opportunity-radar.json",
    "live_opportunity": REPORT_DIR / "live-opportunity-engine.json",
    "daily_stock_screener": REPORT_DIR / "daily-stock-screener.json",
    "daily_edge": REPORT_DIR / "daily-edge-orchestrator.json",
    "trade_signals": REPORT_DIR / "trade-signal-generator.json",
    "options_universe": REPORT_DIR / "daily-options-universe-ranker.json",
    "daily_trade_plan": REPORT_DIR / "daily-trade-plan.json",
    "cheap_asymmetry": REPORT_DIR / "cheap-asymmetry-scanner.json",
    "intraday_opportunity_brief": REPORT_DIR / "intraday-opportunity-brief.json",
    "eod_opportunity_brief": REPORT_DIR / "eod-opportunity-brief.json",
    "deep_liquid_universe": REPORT_DIR / "deep-liquid-universe-scan.json",
}
DEFAULT_OUTCOMES = (DATA_DIR / "pattern_grader_outcomes.jsonl", DATA_DIR / "shadow_outcomes.jsonl")
TOP_SCORE = 93.0


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
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _row_day(row: Mapping[str, Any], inherited: Mapping[str, Any]) -> str | None:
    direct = str(row.get("date") or inherited.get("date") or "")[:10]
    if len(direct) == 10:
        return direct
    stamp = _timestamp(
        row.get("generated_at") or row.get("timestamp") or row.get("as_of_et")
        or row.get("trigger_bar_ts") or row.get("triggered_at")
        or inherited.get("generated_at") or inherited.get("timestamp") or inherited.get("as_of_et")
    )
    return stamp[:10] if stamp else None


def _read_payloads(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        errors = 0
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                errors += 1
                continue
            if isinstance(value, dict):
                rows.append(value)
            else:
                errors += 1
        return rows, errors
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return [], 1
    return ([value] if isinstance(value, dict) else []), (0 if isinstance(value, dict) else 1)


def _score(row: Mapping[str, Any]) -> float | None:
    for key in ("decision_score", "final_score", "score", "setup_score", "confidence_score"):
        value = _number(row.get(key))
        if value is not None:
            return value
    pattern_grade = row.get("pattern_grade") if isinstance(row.get("pattern_grade"), dict) else {}
    return _number(pattern_grade.get("final_score"))


def _looks_like_setup(row: Mapping[str, Any]) -> bool:
    return bool(row.get("symbol") or row.get("instrument")) and any(
        row.get(key) is not None
        for key in ("setup", "setup_family", "pattern_id", "candidate_id", "detection_id", "signal_id", "entry", "trigger")
    )


def _top_tier_basis(row: Mapping[str, Any], source: str) -> str | None:
    if not _looks_like_setup(row):
        return None
    grade = str(row.get("grade") or "").strip().upper()
    if grade == "A+":
        return "explicit_aplus"
    pattern_grade = row.get("pattern_grade") if isinstance(row.get("pattern_grade"), dict) else {}
    if grade == "A" and (source == "pattern_grader" or pattern_grade.get("rubric_version")):
        return "canonical_highest_a"
    score = _score(row)
    return "score_at_least_93" if score is not None and score >= TOP_SCORE else None


def _walk(
    value: Any,
    *,
    source: str,
    day: str,
    inherited: Mapping[str, Any] | None = None,
) -> Iterable[dict[str, Any]]:
    inherited = dict(inherited or {})
    if isinstance(value, list):
        for child in value:
            yield from _walk(child, source=source, day=day, inherited=inherited)
        return
    if not isinstance(value, dict):
        return
    context = dict(inherited)
    for key in ("date", "generated_at", "timestamp", "as_of_et"):
        if value.get(key) is not None:
            context[key] = value[key]
    basis = _top_tier_basis(value, source)
    if basis and _row_day(value, context) == day:
        yield _observation(value, source=source, day=day, context=context, basis=basis)
    for child in value.values():
        if isinstance(child, (dict, list)):
            yield from _walk(child, source=source, day=day, inherited=context)


def _observation(
    row: Mapping[str, Any], *, source: str, day: str, context: Mapping[str, Any], basis: str
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or row.get("instrument") or "UNKNOWN").upper()
    setup = str(row.get("setup") or row.get("setup_family") or row.get("pattern_id") or "unspecified")
    direction = str(row.get("direction") or row.get("side") or "neutral").lower()
    explicit_id = next(
        (str(row[key]) for key in ("detection_id", "candidate_id", "signal_id", "plan_id", "trade_key") if row.get(key)),
        None,
    )
    identity = explicit_id or hashlib.sha256(f"{day}|{source}|{symbol}|{setup}|{direction}".encode()).hexdigest()[:20]
    detected_at = _timestamp(
        row.get("generated_at") or row.get("timestamp") or row.get("trigger_bar_ts")
        or row.get("triggered_at") or context.get("generated_at") or context.get("timestamp") or context.get("as_of_et")
    )
    entry = next((_number(row.get(key)) for key in ("entry", "trigger", "entry_trigger") if _number(row.get(key)) is not None), None)
    invalidation = next((_number(row.get(key)) for key in ("invalidation", "stop") if _number(row.get(key)) is not None), None)
    blockers = [str(item) for item in row.get("blockers", [])] if isinstance(row.get("blockers"), list) else []
    if isinstance(row.get("hard_blockers"), list):
        blockers.extend(str(item) for item in row["hard_blockers"] if isinstance(item, (str, int, float)))
    market_structure = row.get("market_structure") if isinstance(row.get("market_structure"), dict) else {}
    coverage = row.get("timeframe_coverage") if isinstance(row.get("timeframe_coverage"), dict) else market_structure.get("timeframe_coverage") if isinstance(market_structure.get("timeframe_coverage"), dict) else {}
    missing_timeframes = [str(item) for item in coverage.get("missing_required", [])] if isinstance(coverage.get("missing_required"), list) else []
    if missing_timeframes and "incomplete_aplus_timeframe_coverage" not in blockers:
        blockers.append("incomplete_aplus_timeframe_coverage")
    return {
        "review_id": identity,
        "source": source,
        "symbol": symbol,
        "setup": setup,
        "direction": direction,
        "grade": str(row.get("grade") or "A+").upper(),
        "grade_basis": basis,
        "score": _score(row),
        "detected_at": detected_at,
        "entry": entry,
        "invalidation": invalidation,
        "blockers": list(dict.fromkeys(blockers)),
        "timeframe_coverage_status": str(coverage.get("status") or "unavailable"),
        "missing_required_timeframes": missing_timeframes,
    }


def _outcome_index(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for path in paths:
        rows, _errors = _read_payloads(path)
        for row in rows:
            for key in ("detection_id", "candidate_id", "plan_id", "signal_id", "trade_key", "review_id"):
                if row.get(key):
                    index[str(row[key])] = row
    return index


def _outcome_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    available = {
        key: row.get(key)
        for key in ("outcome_r", "realized_r", "won", "pnl", "terminal_reason", "resolved_at", "outcome_60m", "outcome_eod")
        if row.get(key) is not None
    }
    return available


def build_report(
    *,
    day: str | None = None,
    sources: Mapping[str, Path] | None = None,
    outcome_paths: Iterable[Path] | None = None,
    prior_reports: Iterable[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sources = dict(DEFAULT_SOURCES if sources is None else sources)
    outcomes = _outcome_index(tuple(outcome_paths) if outcome_paths is not None else DEFAULT_OUTCOMES)
    observations: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for source, path in sources.items():
        rows, parse_errors = _read_payloads(path)
        source_observations = [observation for row in rows for observation in _walk(row, source=source, day=day)]
        observations.extend(source_observations)
        modified_at: datetime | None = None
        if path.exists():
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_minutes = max(0.0, (now - modified_at).total_seconds() / 60.0) if modified_at else None
        inventory.append({
            "source": source,
            "path": str(path),
            "status": "missing" if not path.exists() else "parse_error" if parse_errors else "reviewed",
            "freshness": "missing" if modified_at is None else "fresh" if age_minutes <= 36 * 60 else "stale",
            "last_modified_at": modified_at.isoformat().replace("+00:00", "Z") if modified_at else None,
            "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
            "payload_count": len(rows),
            "parse_error_count": parse_errors,
            "top_tier_observation_count": len(source_observations),
            "execution_enabled": False,
            "can_submit_orders": False,
        })

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for observation in observations:
        groups.setdefault((observation["source"], observation["review_id"]), []).append(observation)
    items: list[dict[str, Any]] = []
    for (_source, review_id), snapshots in sorted(groups.items()):
        snapshots.sort(key=lambda row: str(row.get("detected_at") or ""))
        latest = snapshots[-1]
        outcome = outcomes.get(review_id)
        blockers = sorted({blocker for row in snapshots for blocker in row["blockers"]})
        missing_geometry = latest.get("entry") is None or latest.get("invalidation") is None
        if outcome:
            verdict = "reviewed_with_resolved_outcome"
        elif blockers:
            verdict = "reviewed_blocked_not_trade_ready"
        elif missing_geometry:
            verdict = "reviewed_missing_trade_geometry"
        else:
            verdict = "reviewed_outcome_pending"
        items.append({
            **latest,
            "origin_date": day,
            "is_carry_forward": False,
            "first_detected_at": snapshots[0].get("detected_at"),
            "last_detected_at": latest.get("detected_at"),
            "observation_count": len(snapshots),
            "max_score": max((row["score"] for row in snapshots if row.get("score") is not None), default=None),
            "blockers": blockers,
            "geometry_complete": not missing_geometry,
            "system_review_status": "reviewed",
            "outcome_review_status": "resolved" if outcome else "pending",
            "outcome": _outcome_summary(outcome or {}),
            "verdict": verdict,
            "execution_enabled": False,
            "can_submit_orders": False,
        })

    current_keys = {(row["source"], row["review_id"]) for row in items}
    pending_prior: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    for prior in prior_reports or ():
        prior_day = str(prior.get("date") or "")[:10]
        if prior_day and prior_day > day:
            continue
        prior_items = prior.get("items") if isinstance(prior.get("items"), list) else []
        for prior_item in prior_items:
            if not isinstance(prior_item, dict):
                continue
            source = str(prior_item.get("source") or "unknown")
            review_id = str(prior_item.get("review_id") or "")
            if not review_id:
                continue
            key = (source, review_id)
            if prior_item.get("outcome_review_status") == "pending":
                pending_prior[(source, review_id)] = (prior_day, prior_item)
            else:
                pending_prior.pop(key, None)

    carried_count = 0
    for key, (prior_day, prior_item) in sorted(pending_prior.items()):
        if key in current_keys:
            continue
        outcome = outcomes.get(key[1])
        carried = dict(prior_item)
        carried.update({
            "origin_date": str(prior_item.get("origin_date") or prior_day or day),
            "is_carry_forward": True,
            "system_review_status": "reviewed",
            "outcome_review_status": "resolved" if outcome else "pending",
            "outcome": _outcome_summary(outcome or {}),
            "verdict": "reviewed_with_resolved_outcome" if outcome else "reviewed_outcome_pending",
            "execution_enabled": False,
            "can_submit_orders": False,
        })
        items.append(carried)
        carried_count += 1

    available_sources = sum(row["status"] == "reviewed" for row in inventory)
    missing_or_bad = len(inventory) - available_sources
    resolved_count = sum(row["outcome_review_status"] == "resolved" for row in items)
    summary = {
        "declared_source_count": len(inventory),
        "reviewed_source_count": available_sources,
        "source_coverage_pct": round(100.0 * available_sources / len(inventory), 1) if inventory else 100.0,
        "top_tier_observation_count": len(observations),
        "distinct_setup_count": len(items),
        "current_distinct_setup_count": len(items) - carried_count,
        "carried_followup_count": carried_count,
        "system_reviewed_setup_count": len(items),
        "system_review_coverage_pct": 100.0,
        "outcome_resolved_count": resolved_count,
        "outcome_followup_count": len(items) - resolved_count,
        "blocked_or_incomplete_count": sum(bool(row["blockers"]) or not row["geometry_complete"] for row in items),
    }
    report = {
        "schema_version": 1,
        "date": day,
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "provider": "daily_aplus_review",
        "mode": "read_only_daily_coverage_audit",
        "review_status": "complete" if missing_or_bad == 0 else "attention_required",
        "definition": "Explicit A+, canonical Pattern Grade A, or trade-like score >=93; scores are not probabilities.",
        "summary": summary,
        "source_inventory": inventory,
        "items": items,
        "warnings": [
            "Every enumerated top-tier setup receives a system review; unresolved outcomes remain open follow-up items.",
            "Missing declared sources fail coverage closed because zero candidates cannot be distinguished from a failed producer.",
            "A+ is setup quality, not guaranteed profitability and not permission to execute.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    fingerprint = json.dumps({"date": day, "summary": summary, "items": items, "sources": inventory}, sort_keys=True, separators=(",", ":"))
    report["snapshot_id"] = hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
    return report


def write_report(report: Mapping[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def append_if_changed(report: Mapping[str, Any], path: Path = LOG_PATH) -> bool:
    existing, _errors = _read_payloads(path)
    if any(row.get("snapshot_id") == report.get("snapshot_id") for row in existing):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    return True


def print_report(report: Mapping[str, Any]) -> None:
    summary = report["summary"]
    print("\nDaily A+ Review | read-only")
    print("=" * 72)
    print(
        f"date={report['date']} status={report['review_status']} "
        f"observations={summary['top_tier_observation_count']} setups={summary['distinct_setup_count']} "
        f"system_coverage={summary['system_review_coverage_pct']}% source_coverage={summary['source_coverage_pct']}%"
    )
    print(f"outcomes_resolved={summary['outcome_resolved_count']} followups={summary['outcome_followup_count']}")
    for item in report["items"][:20]:
        print(f"- {item['symbol']} {item['setup']} {item['grade']} {item['verdict']}")
    print("No orders placed. No execution authority changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    prior_reports, _errors = _read_payloads(args.log_path)
    report = build_report(day=args.date, prior_reports=prior_reports)
    write_report(report, args.report_path)
    appended = append_if_changed(report, args.log_path)
    if args.print_output:
        print_report(report)
        print(f"snapshot_appended={str(appended).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
