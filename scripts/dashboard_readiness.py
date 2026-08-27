#!/usr/bin/env python3
"""Audit dashboard build, runtime producers, and evidence maturity separately."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
REPORT_PATH = REPORT_DIR / "dashboard-readiness.json"

BUILD_COMPONENTS = {
    "pattern_scanner": "scripts/pattern_grader_scanner.py",
    "intraday_radar": "scripts/intraday_opportunity_radar.py",
    "live_opportunity_engine": "scripts/live_opportunity_engine.py",
    "live_trading_cockpit": "scripts/live_trading_cockpit.py",
    "move_ground_truth": "scripts/build_move_ground_truth.py",
    "detection_scorecard": "scripts/detection_scorecard.py",
    "probability_calibration": "scripts/grade_probability_service.py",
    "daily_aplus_review": "scripts/daily_aplus_review.py",
    "options_reference_refresh": "scripts/options_reference_refresh.py",
    "options_feed_gate": "scripts/options_feed_qualification.py",
    "manual_execution_quality": "scripts/manual_execution_quality.py",
    "broker_fill_observer": "scripts/broker_fill_observer.py",
    "evidence_chain_runner": "scripts/run_dashboard_evidence_chain.ps1",
    "move_ground_truth_runner": "scripts/run_move_universe_ground_truth.ps1",
    "readiness_dashboard": "frontend/src/components/trading/SystemReadinessGate.tsx",
}

CORE_LIQUID_LEADERS = {
    "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "AMZN",
    "META", "GOOGL", "TSLA", "AMD", "AVGO", "MSTR", "COIN",
}
LIVE_REPORT_MAX_AGE_SECONDS = 20 * 60
EOD_EVIDENCE_MAX_AGE_SECONDS = 36 * 60 * 60


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _percent(rows: list[dict[str, Any]]) -> float:
    return round(100.0 * sum(bool(row["ready"]) for row in rows) / len(rows), 1) if rows else 100.0


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(report: dict[str, Any], now: datetime) -> float | None:
    stamp = _parse_time(report.get("generated_at") or report.get("timestamp"))
    if stamp is None:
        return None
    return max(0.0, (now - stamp).total_seconds())


def _gate(
    gate_id: str,
    report: dict[str, Any],
    ready: bool,
    reason: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "ready": bool(ready),
        "reason": reason,
        "generated_at": report.get("generated_at") or report.get("timestamp"),
        **details,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _lane(
    lane_id: str,
    gate_ids: tuple[str, ...],
    runtime_by_id: dict[str, dict[str, Any]],
    *,
    build_by_id: dict[str, dict[str, Any]],
    build_ids: tuple[str, ...] = (),
    message_ready: str,
    message_blocked: str,
) -> dict[str, Any]:
    failed = [gate_id for gate_id in gate_ids if not runtime_by_id.get(gate_id, {}).get("ready")]
    failed_build = [gate_id for gate_id in build_ids if not build_by_id.get(gate_id, {}).get("ready")]
    ready = not failed and not failed_build
    denominator = len(gate_ids) + len(build_ids)
    passed = denominator - len(failed) - len(failed_build)
    return {
        "id": lane_id,
        "ready": ready,
        "status": "operational" if ready else "fail_closed",
        "percent": round(100.0 * passed / denominator, 1) if denominator else 100.0,
        "gate_ids": list(gate_ids),
        "failed_gates": failed,
        "failed_build_components": failed_build,
        "message": message_ready if ready else message_blocked,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_readiness(
    *, root: Path = ROOT, report_dir: Path = REPORT_DIR, now: datetime | None = None
) -> dict[str, Any]:
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    build_gates = [
        _gate(name, {}, (root / relative).is_file(), relative)
        for name, relative in BUILD_COMPONENTS.items()
    ]
    build_pct = _percent(build_gates)

    scanner = _read(report_dir / "pattern-grader-grades.json")
    scanner_reconciliation = scanner.get("scan_reconciliation") if isinstance(scanner.get("scan_reconciliation"), dict) else {}
    move = _read(report_dir / "move-ground-truth-summary.json")
    intraday = _read(report_dir / "intraday-opportunity-radar.json")
    intraday_coverage = intraday.get("coverage") if isinstance(intraday.get("coverage"), dict) else {}
    live = _read(report_dir / "live-opportunity-engine.json")
    live_coverage = live.get("stream_coverage") if isinstance(live.get("stream_coverage"), dict) else {}
    scorecard = _read(report_dir / "detection-scorecard-rolling.json")
    pattern_coverage = scorecard.get("pattern_coverage") if isinstance(scorecard.get("pattern_coverage"), dict) else {}
    opportunity = pattern_coverage.get("opportunity_coverage") if isinstance(pattern_coverage.get("opportunity_coverage"), dict) else {}
    daily = _read(report_dir / "daily-aplus-review.json")
    daily_summary = daily.get("summary") if isinstance(daily.get("summary"), dict) else {}
    options = _read(report_dir / "options-feed-qualification.json")
    options_refresh = _read(report_dir / "options-reference-refresh.json")
    manual = _read(report_dir / "manual-execution-quality.json")
    broker = _read(report_dir / "broker-fill-observer.json")
    calibration = _read(report_dir / "grade-probability-calibration.json")

    scanner_age = _age_seconds(scanner, evaluated_at)
    intraday_age = _age_seconds(intraday, evaluated_at)
    live_age = _age_seconds(live, evaluated_at)
    options_refresh_age = _age_seconds(options_refresh, evaluated_at)
    move_age = _age_seconds(move, evaluated_at)
    scorecard_age = _age_seconds(scorecard, evaluated_at)
    daily_age = _age_seconds(daily, evaluated_at)
    calibration_age = _age_seconds(calibration, evaluated_at)
    reserved_core = {
        str(symbol).upper()
        for symbol in intraday_coverage.get("reserved_liquid_core", [])
    }
    core_missing = sorted(CORE_LIQUID_LEADERS - reserved_core)
    stream_core_missing = [str(value) for value in live_coverage.get("mandatory_core_missing", [])]
    options_summary = options.get("summary") if isinstance(options.get("summary"), dict) else {}

    runtime_gates = [
        _gate(
            "pattern_scanner",
            scanner,
            scanner_reconciliation.get("denominator_reconciled") is True
            and int(scanner_reconciliation.get("producer_failure_count") or 0) == 0
            and scanner_age is not None
            and scanner_age <= LIVE_REPORT_MAX_AGE_SECONDS,
            "canonical scanner denominator reconciled",
            age_seconds=round(scanner_age, 1) if scanner_age is not None else None,
        ),
        _gate(
            "intraday_radar",
            intraday,
            intraday_age is not None
            and intraday_age <= LIVE_REPORT_MAX_AGE_SECONDS
            and intraday.get("operational_health") == "ok"
            and not intraday.get("errors")
            and float(intraday_coverage.get("snapshot_coverage_pct") or 0) >= 95.0
            and int(intraday_coverage.get("symbols_evaluated") or 0) >= 100
            and int(intraday_coverage.get("symbols_with_5m_bars") or 0) >= 100
            and not core_missing,
            "fresh healthy market-wide radar covers at least 95%, evaluates and bars at least 100 symbols, and reserves every core liquid leader",
            age_seconds=round(intraday_age, 1) if intraday_age is not None else None,
            core_missing=core_missing,
        ),
        _gate(
            "live_opportunity_engine",
            live,
            live_age is not None
            and live_age <= LIVE_REPORT_MAX_AGE_SECONDS
            and live.get("stream_status") in {"connected", "connected_hybrid"}
            and not stream_core_missing,
            "fresh hybrid stream is connected and every mandatory core leader is covered",
            age_seconds=round(live_age, 1) if live_age is not None else None,
            core_missing=stream_core_missing,
        ),
        _gate(
            "move_ground_truth",
            move,
            move.get("producer_healthy") is True
            and move_age is not None
            and move_age <= EOD_EVIDENCE_MAX_AGE_SECONDS,
            "fresh independent MOVE producer acquired all required sources",
            age_seconds=round(move_age, 1) if move_age is not None else None,
        ),
        _gate(
            "detection_scorecard",
            scorecard,
            scorecard_age is not None
            and scorecard_age <= EOD_EVIDENCE_MAX_AGE_SECONDS
            and isinstance(scorecard.get("latest_session"), dict)
            and isinstance(scorecard.get("latest_session", {}).get("stage_counts"), dict),
            "fresh detection scorecard contains a staged latest-session denominator",
            age_seconds=round(scorecard_age, 1) if scorecard_age is not None else None,
        ),
        _gate(
            "daily_aplus_review",
            daily,
            daily.get("review_status") == "complete"
            and daily_age is not None
            and daily_age <= EOD_EVIDENCE_MAX_AGE_SECONDS
            and float(daily_summary.get("overall_review_coverage_pct") or 0) == 100.0,
            "all declared A+ sources reviewed in a fresh EOD report",
            age_seconds=round(daily_age, 1) if daily_age is not None else None,
        ),
        _gate(
            "options_reference_refresh",
            options_refresh,
            options_refresh_age is not None
            and options_refresh_age <= LIVE_REPORT_MAX_AGE_SECONDS
            and int(options_refresh.get("captured_count") or 0) > 0,
            "current core-leader option reference contracts were refreshed before feed qualification",
            age_seconds=round(options_refresh_age, 1) if options_refresh_age is not None else None,
            captured_count=int(options_refresh.get("captured_count") or 0),
        ),
        _gate(
            "options_feed_gate",
            options,
            options.get("status") == "manual_execution_reference_available"
            or int(options_summary.get("manual_execution_qualified") or 0) > 0,
            "at least one current OPRA-qualified manual execution reference is available",
        ),
        _gate(
            "manual_execution_quality",
            manual,
            manual.get("status") in {"awaiting_observations", "followup_required", "complete"},
            "manual execution-quality report produced",
        ),
        _gate("broker_fill_observer", broker, broker.get("status") in {"ok", "no_fills"}, "read-only broker fill observation succeeded"),
        _gate(
            "probability_calibration",
            calibration,
            calibration_age is not None
            and calibration_age <= EOD_EVIDENCE_MAX_AGE_SECONDS
            and "eligible_outcomes" in calibration
            and isinstance(calibration.get("buckets"), list),
            "fresh calibration report contains its outcome denominator and buckets",
            age_seconds=round(calibration_age, 1) if calibration_age is not None else None,
        ),
    ]
    runtime_pct = _percent(runtime_gates)
    build_by_id = {row["id"]: row for row in build_gates}
    runtime_by_id = {row["id"]: row for row in runtime_gates}
    lanes = {
        "equity_scanner": _lane(
            "equity_scanner",
            ("pattern_scanner", "intraday_radar", "live_opportunity_engine"),
            runtime_by_id,
            build_by_id=build_by_id,
            build_ids=("pattern_scanner", "intraday_radar", "live_opportunity_engine", "live_trading_cockpit", "readiness_dashboard"),
            message_ready="Equity discovery, core-liquid coverage, and the completed-bar live stream are operational for manual review.",
            message_blocked="Equity review is fail-closed until every scanner, freshness, coverage, and stream gate passes.",
        ),
        "options_manual_reference": _lane(
            "options_manual_reference",
            ("pattern_scanner", "intraday_radar", "live_opportunity_engine", "options_reference_refresh", "options_feed_gate"),
            runtime_by_id,
            build_by_id=build_by_id,
            build_ids=("options_reference_refresh", "options_feed_gate"),
            message_ready="The equity setup and current OPRA-qualified manual price reference are both available.",
            message_blocked="Options remain blocked; context may be displayed, but no contract entry should be inferred without a current qualified reference.",
        ),
        "research_evidence": _lane(
            "research_evidence",
            ("move_ground_truth", "detection_scorecard", "daily_aplus_review", "probability_calibration"),
            runtime_by_id,
            build_by_id=build_by_id,
            message_ready="The outcome, denominator, review, and calibration producers are available for research review.",
            message_blocked="Research promotion remains fail-closed while an evidence producer or review denominator is incomplete.",
        ),
        "execution_observability": _lane(
            "execution_observability",
            ("manual_execution_quality", "broker_fill_observer"),
            runtime_by_id,
            build_by_id=build_by_id,
            message_ready="Manual observations and read-only broker fill reconciliation are available.",
            message_blocked="Execution-quality review is fail-closed until its read-only observers report.",
        ),
    }

    buckets = [row for row in calibration.get("buckets", []) if isinstance(row, dict)]
    probabilities = [row.get("probability") for row in buckets if isinstance(row.get("probability"), dict)]
    qualified_buckets = sum(
        row.get("status") == "local_forward_validated" or row.get("ranking_eligible") is True
        for row in probabilities
    )
    eligible_outcomes = int(calibration.get("eligible_outcomes") or 0)
    independent_dates = max((int(row.get("independent_dates") or 0) for row in probabilities), default=0)
    probability_claims_qualified = qualified_buckets > 0
    runtime_ready = runtime_pct == 100.0
    build_ready = build_pct == 100.0
    equity_ready = lanes["equity_scanner"]["ready"]
    options_ready = lanes["options_manual_reference"]["ready"]
    research_ready = lanes["research_evidence"]["ready"]
    return {
        "schema_version": 1,
        "generated_at": evaluated_at.isoformat().replace("+00:00", "Z"),
        "mode": "read_only_operational_readiness",
        "build": {
            "status": "installed" if build_ready else "incomplete",
            "percent": build_pct,
            "gates": build_gates,
        },
        "runtime": {
            "status": "operational" if runtime_ready else "operational_partial" if equity_ready else "attention_required",
            "percent": runtime_pct,
            "gates": runtime_gates,
        },
        "lanes": lanes,
        "evidence": {
            "status": "qualified" if probability_claims_qualified else "collecting",
            "ranking_qualified_bucket_count": qualified_buckets,
            "eligible_outcomes": eligible_outcomes,
            "independent_dates": independent_dates,
            "move_metrics_qualified": move.get("metrics_qualified") is True,
            "opportunity_metrics_qualified": opportunity.get("metrics_qualified") is True,
            "message": (
                "At least one calibrated probability bucket is ranking-qualified."
                if probability_claims_qualified
                else "The system is collecting outcomes; setup grades are not calibrated win probabilities."
            ),
        },
        "ready_for_manual_review": equity_ready,
        "ready_for_equity_manual_review": equity_ready,
        "ready_for_options_manual_review": options_ready,
        "ready_for_research_promotion_review": research_ready,
        "all_lanes_ready": build_ready and all(lane["ready"] for lane in lanes.values()),
        "probability_claims_qualified": probability_claims_qualified,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_readiness(root=args.root, report_dir=args.report_dir)
    _write_atomic(args.output, report)
    print(
        f"dashboard_readiness build={report['build']['percent']} "
        f"runtime={report['runtime']['percent']} evidence={report['evidence']['status']}"
    )
    return 0 if report["build"]["percent"] == 100.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
