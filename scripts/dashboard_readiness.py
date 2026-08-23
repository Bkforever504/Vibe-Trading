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
    "move_ground_truth": "scripts/build_move_ground_truth.py",
    "detection_scorecard": "scripts/detection_scorecard.py",
    "probability_calibration": "scripts/grade_probability_service.py",
    "daily_aplus_review": "scripts/daily_aplus_review.py",
    "options_feed_gate": "scripts/options_feed_qualification.py",
    "manual_execution_quality": "scripts/manual_execution_quality.py",
    "broker_fill_observer": "scripts/broker_fill_observer.py",
    "evidence_chain_runner": "scripts/run_dashboard_evidence_chain.ps1",
    "move_ground_truth_runner": "scripts/run_move_universe_ground_truth.ps1",
    "readiness_dashboard": "frontend/src/components/trading/SystemReadinessGate.tsx",
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _percent(rows: list[dict[str, Any]]) -> float:
    return round(100.0 * sum(bool(row["ready"]) for row in rows) / len(rows), 1) if rows else 100.0


def _gate(gate_id: str, report: dict[str, Any], ready: bool, reason: str) -> dict[str, Any]:
    return {
        "id": gate_id,
        "ready": bool(ready),
        "reason": reason,
        "generated_at": report.get("generated_at") or report.get("timestamp"),
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
    scorecard = _read(report_dir / "detection-scorecard-rolling.json")
    pattern_coverage = scorecard.get("pattern_coverage") if isinstance(scorecard.get("pattern_coverage"), dict) else {}
    opportunity = pattern_coverage.get("opportunity_coverage") if isinstance(pattern_coverage.get("opportunity_coverage"), dict) else {}
    daily = _read(report_dir / "daily-aplus-review.json")
    daily_summary = daily.get("summary") if isinstance(daily.get("summary"), dict) else {}
    options = _read(report_dir / "options-feed-qualification.json")
    manual = _read(report_dir / "manual-execution-quality.json")
    broker = _read(report_dir / "broker-fill-observer.json")
    calibration = _read(report_dir / "grade-probability-calibration.json")

    runtime_gates = [
        _gate(
            "pattern_scanner",
            scanner,
            scanner_reconciliation.get("denominator_reconciled") is True
            and int(scanner_reconciliation.get("producer_failure_count") or 0) == 0,
            "canonical scanner denominator reconciled",
        ),
        _gate("move_ground_truth", move, move.get("producer_healthy") is True, "independent MOVE producer acquired all required sources"),
        _gate("detection_scorecard", scorecard, bool(scorecard), "detection scorecard report produced"),
        _gate(
            "daily_aplus_review",
            daily,
            daily.get("review_status") == "complete"
            and float(daily_summary.get("overall_review_coverage_pct") or 0) == 100.0,
            "all declared A+ sources reviewed",
        ),
        _gate(
            "options_feed_gate",
            options,
            options.get("status") in {"context_only", "manual_execution_reference_available"},
            "fresh options context observed; manual reference remains separately gated",
        ),
        _gate(
            "manual_execution_quality",
            manual,
            manual.get("status") in {"awaiting_observations", "followup_required", "complete"},
            "manual execution-quality report produced",
        ),
        _gate("broker_fill_observer", broker, broker.get("status") in {"ok", "no_fills"}, "read-only broker fill observation succeeded"),
        _gate("probability_calibration", calibration, bool(calibration), "calibration report produced"),
    ]
    runtime_pct = _percent(runtime_gates)

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
            "status": "operational" if runtime_ready else "attention_required",
            "percent": runtime_pct,
            "gates": runtime_gates,
        },
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
        "ready_for_manual_review": build_ready and runtime_ready,
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
