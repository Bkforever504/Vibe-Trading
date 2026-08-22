#!/usr/bin/env python3
"""Audit whether the intraday radar detected the session's largest movers."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_REPORT_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
RADAR_LOG_PATH = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "daily-move-coverage-review.json"
LEDGER_PATH = ROOT / "data" / "daily_move_coverage_review.jsonl"


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
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _execution_eligible(candidate: dict[str, Any]) -> bool:
    """Separate setup quality from the radar's intentional no-order authority."""
    authority_only = {"strategy_confirmation_and_revalidation_required"}
    blockers = {
        str(value) for value in candidate.get("blockers") or []
        if str(value) not in authority_only
    }
    return str(candidate.get("state") or "") in {"watch", "precision_watch"} and not blockers


def build_review(latest: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    review_date = str(latest.get("date") or "")[:10]
    sessions = [row for row in history if str(row.get("date") or "")[:10] == review_date]
    first_seen: dict[str, dict[str, Any]] = {}
    discovered_at: dict[str, str] = {}
    for report in sessions:
        timestamp = str(report.get("as_of_et") or report.get("generated_at") or "")
        for symbol in report.get("all_discovered_symbols") or []:
            discovered_at.setdefault(str(symbol).upper(), timestamp)
        for candidate in report.get("ranked_candidates") or []:
            if not isinstance(candidate, dict) or not candidate.get("symbol"):
                continue
            symbol = str(candidate["symbol"]).upper()
            first_seen.setdefault(symbol, {"timestamp": timestamp, "candidate": candidate})

    movers = [row for row in latest.get("market_movers") or [] if isinstance(row, dict)]
    movers.sort(key=lambda row: abs(_number(row.get("percent_change")) or 0.0), reverse=True)
    audited: list[dict[str, Any]] = []
    for mover in movers:
        symbol = str(mover.get("symbol") or "").upper()
        final_change = _number(mover.get("percent_change"))
        seen = first_seen.get(symbol)
        if seen:
            candidate = seen["candidate"]
            first_change = _number(candidate.get("change_pct"))
            final_magnitude = abs(final_change or 0.0)
            first_magnitude = abs(first_change or 0.0)
            remaining_share = max(final_magnitude - first_magnitude, 0.0) / final_magnitude if final_magnitude else 0.0
            classification = "detected_early" if remaining_share >= 0.35 else "detected_late"
            execution_eligible = _execution_eligible(candidate)
            if classification == "detected_early" and execution_eligible:
                actionability = "actionable_early"
            elif classification == "detected_early":
                actionability = "early_but_blocked"
            elif execution_eligible:
                actionability = "eligible_but_late"
            else:
                actionability = "late_and_blocked"
            audited.append(
                {
                    **mover,
                    "classification": classification,
                    "first_detected_at": seen["timestamp"],
                    "first_detected_change_pct": first_change,
                    "remaining_move_share_pct": round(remaining_share * 100.0, 2),
                    "first_grade": candidate.get("grade"),
                    "first_state": candidate.get("state"),
                    "filter_reasons": candidate.get("blockers") or [],
                    "execution_eligible_at_first_detection": execution_eligible,
                    "actionability": actionability,
                }
            )
        elif symbol in discovered_at:
            audited.append(
                {
                    **mover,
                    "classification": "discovered_not_evaluated",
                    "first_detected_at": discovered_at[symbol],
                    "filter_reasons": ["not_selected_for_intraday_bar_budget"],
                    "execution_eligible_at_first_detection": False,
                    "actionability": "not_evaluated",
                }
            )
        else:
            audited.append({
                **mover,
                "classification": "missed",
                "filter_reasons": ["not_returned_by_discovery_sources"],
                "execution_eligible_at_first_detection": False,
                "actionability": "missed",
            })

    counts: dict[str, int] = {}
    for row in audited:
        key = str(row.get("classification") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    evaluated = counts.get("detected_early", 0) + counts.get("detected_late", 0)
    discovered = evaluated + counts.get("discovered_not_evaluated", 0)
    execution_eligible = sum(bool(row.get("execution_eligible_at_first_detection")) for row in audited)
    actionable_early = sum(row.get("actionability") == "actionable_early" for row in audited)
    return {
        "schema_version": 2,
        "provider": "daily_move_coverage_review",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": review_date,
        "mode": "read_only_accountability",
        "execution_enabled": False,
        "can_submit_orders": False,
        "summary": {
            "movers_audited": len(audited),
            "source_discovery_count": discovered,
            "source_discovery_recall_pct": round(discovered / len(audited) * 100.0, 2) if audited else None,
            "evaluated_count": evaluated,
            "evaluated_recall_pct": round(evaluated / len(audited) * 100.0, 2) if audited else None,
            "early_detection_count": counts.get("detected_early", 0),
            "late_detection_count": counts.get("detected_late", 0),
            "execution_eligible_at_first_detection_count": execution_eligible,
            "actionable_early_count": actionable_early,
            "actionable_early_recall_pct": round(actionable_early / len(audited) * 100.0, 2) if audited else None,
            "missed_count": counts.get("missed", 0),
            "classification_counts": counts,
            "radar_snapshots_reviewed": len(sessions),
        },
        "moves": audited,
        "warnings": [
            "Detection is not the same as a profitable or executable entry.",
            "Actionable early requires both meaningful move remaining and no setup-quality blocker at first evaluation.",
            "The review uses Alpaca's final mover list and the radar snapshots actually recorded.",
            "No hindsight-generated trade fills or profit claims are included.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-report", type=Path, default=RADAR_REPORT_PATH)
    parser.add_argument("--radar-log", type=Path, default=RADAR_LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_review(_read_json(args.radar_report), _read_jsonl(args.radar_log))
    _atomic_json(args.report_path, report)
    args.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            f"Move coverage: audited={summary['movers_audited']} "
            f"discovered={summary['source_discovery_count']} evaluated={summary['evaluated_count']} "
            f"early={summary['early_detection_count']} late={summary['late_detection_count']} "
            f"missed={summary['missed_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
