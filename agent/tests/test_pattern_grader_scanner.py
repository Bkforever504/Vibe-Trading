from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.pattern_grader_scanner import (
    append_new_rows,
    build_pattern_report,
    project_snapshot,
)


NOW = datetime(2026, 8, 21, 15, 35, tzinfo=timezone.utc)


def _snapshot() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-08-21T15:35:00Z",
        "mode": "read_only_streaming_research",
        "stream_status": "connected",
        "feed": {
            "provider": "alpaca",
            "feed": "iex",
            "label": "alpaca_iex_websocket",
            "entitlement_status": "configured_not_verified",
            "last_event_at": "2026-08-21T15:34:59Z",
        },
        "market_structure_watchlist": [
            {
                "symbol": "SPY",
                "grade": "A",
                "score": 89.5,
                "decision": "READY_TO_REVIEW",
                "pattern_grade": {
                    "rubric_version": "pattern_grade_v1",
                    "final_score": 89.5,
                    "grade": "A",
                    "validation_status": "UNCALIBRATED",
                },
                "best_setup": {
                    "pattern_id": "ict_cisd_universal_model",
                    "family": "liquidity_delivery",
                    "direction": "bullish",
                    "trigger_state": "confirmed",
                    "trigger": 650.25,
                    "invalidation": 648.75,
                    "reason": "Causal sequence confirmed.",
                },
                "entry_plan": {
                    "trigger": 650.25,
                    "entry_zone": {"low": 650.25, "high": 650.45},
                    "invalidation": 648.75,
                },
                "exit_plan": {
                    "targets": [{"name": "target_2r", "price": 653.25}],
                    "time_stop_bars": 12,
                },
                "hard_blockers": [],
                "timeframe_coverage": {
                    "status": "complete_for_aplus_review",
                    "missing_required": [],
                },
                "timeframe_alignment": {"state": "aligned"},
                "freshness": "live",
                "source_labels": ["completed_5m_bars", "alpaca_iex"],
            },
            {
                "symbol": "QQQ",
                "grade": "D",
                "score": 41.0,
                "decision": "STAND_ASIDE",
                "pattern_grade": {"rubric_version": "pattern_grade_v1", "final_score": 41.0, "grade": "D"},
                "best_setup": None,
                "hard_blockers": ["incomplete_aplus_timeframe_coverage"],
                "timeframe_coverage": {
                    "status": "incomplete_for_aplus_review",
                    "missing_required": ["1d"],
                },
                "freshness": "live",
                "source_labels": ["completed_5m_bars", "alpaca_iex"],
            },
        ],
        "candidates": [
            {
                "candidate_id": "2026-08-21:SPY:ict_cisd_universal_model",
                "symbol": "SPY",
                "asset_class": "equity",
                "setup_family": "ict_cisd_universal_model",
                "direction": "bullish",
                "grade": "A",
                "decision_score": 89.5,
                "state": "READY_TO_REVIEW",
                "bar_completed_at": "2026-08-21T15:30:00Z",
                "entry": 650.25,
                "invalidation": 648.75,
                "targets": [{"name": "target_2r", "price": 653.25}],
                "reward_risk_after_friction": 1.91,
                "blockers": [],
                "quote": {
                    "bid": 650.24,
                    "ask": 650.26,
                    "timestamp": "2026-08-21T15:34:59Z",
                    "freshness": "live",
                    "spread_bps": 0.31,
                },
                "market_structure": {
                    "pattern_grade": {
                        "rubric_version": "pattern_grade_v1",
                        "final_score": 89.5,
                        "grade": "A",
                        "validation_status": "UNCALIBRATED",
                    },
                    "best_setup": {
                        "pattern_id": "ict_cisd_universal_model",
                        "family": "liquidity_delivery",
                        "direction": "bullish",
                        "trigger_state": "confirmed",
                        "trigger": 650.25,
                        "invalidation": 648.75,
                    },
                    "entry_plan": {"entry_zone": {"low": 650.25, "high": 650.45}},
                    "exit_plan": {"time_stop_bars": 12},
                    "timeframe_coverage": {
                        "status": "complete_for_aplus_review",
                        "missing_required": [],
                    },
                    "timeframe_alignment": {"state": "aligned"},
                },
                "source_labels": ["alpaca_iex_websocket", "completed_5m_bars"],
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def test_projection_builds_stable_causal_envelope_and_complete_denominator() -> None:
    first = project_snapshot(_snapshot(), now=NOW)
    second = project_snapshot(_snapshot(), now=NOW)

    assert first == second
    assert len(first["detections"]) == 1
    row = first["detections"][0]
    assert row["detection_id"] == row["lifecycle_id"]
    assert row["detection_id"].startswith("pd-")
    assert row["trigger_bar_ts"] == "2026-08-21T15:30:00Z"
    assert row["pattern_id"] == "ict_cisd_universal_model"
    assert row["trigger_timeframe"] == "5m"
    assert row["plan_hash"].startswith("plan-")
    assert row["producer_aliases"] == ["2026-08-21:SPY:ict_cisd_universal_model"]
    assert row["feed_quality"]["venue_coverage"] == "iex_single_venue_not_consolidated_sip"
    assert row["pattern_grade"]["validation_status"] == "UNCALIBRATED"
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False

    reconciliation = first["scan_reconciliation"]
    assert reconciliation == {
        "eligible_symbol_count": 2,
        "evaluated_symbol_count": 2,
        "data_blocked_symbol_count": 1,
        "emitted_detection_count": 1,
        "abstained_symbol_count": 1,
        "producer_failure_count": 0,
        "denominator_reconciled": True,
    }


def test_append_is_snapshot_idempotent_but_preserves_lifecycle_updates(tmp_path: Path) -> None:
    ledger = tmp_path / "pattern_grader_log.jsonl"
    projected = project_snapshot(_snapshot(), now=NOW)
    row = projected["detections"][0]

    assert append_new_rows(ledger, [row]) == 1
    assert append_new_rows(ledger, [row]) == 0

    changed = {**row, "grade": "B", "score": 82.0, "snapshot_id": "snapshot-changed"}
    assert append_new_rows(ledger, [changed]) == 1
    saved = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(saved) == 2
    assert saved[0]["detection_id"] == saved[1]["detection_id"]


def test_report_keeps_grade_counts_separate_from_probability(tmp_path: Path) -> None:
    projected = project_snapshot(_snapshot(), now=NOW)
    report = build_pattern_report(
        projected["detections"],
        scan_reconciliation=projected["scan_reconciliation"],
        now=NOW,
    )

    assert report["summary"]["grade_counts"] == {"A": 1}
    assert report["summary"]["a_grade_count"] == 1
    assert report["summary"]["qualified_probability_count"] == 0
    assert report["latest_detections"][0]["probability"]["status"] == "not_calibrated"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_scheduler_runs_intraday_and_close_pattern_evidence_pipeline() -> None:
    repo = Path(__file__).resolve().parents[2]
    runner = (repo / "scripts" / "run_pattern_grader_pipeline.ps1").read_text(encoding="utf-8")
    register = (repo / "scripts" / "register_pattern_grader_tasks.ps1").read_text(encoding="utf-8")

    assert "pattern_grader_scanner.py" in runner
    assert "$LASTEXITCODE" in runner
    assert "pattern-grader-pipeline.log" in runner
    assert "PatternGrader-Scanner-Intraday" in register
    assert "PatternGrader-Aggregator" in register
    assert '"MON,TUE,WED,THU,FRI"' in register
    assert '"/RI", "5"' in register
    assert '"/RL", "LIMITED"' in register
    assert "Saturday" in runner and "Sunday" in runner
    assert "Read-only pattern evidence" in register
