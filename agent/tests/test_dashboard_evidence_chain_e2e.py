from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.detection_scorecard import build_rolling, build_scorecard
from scripts.grade_probability_service import build_calibration
from scripts.live_trading_cockpit import build_cockpit


NOW = datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)


def _write(report_dir: Path, name: str, payload: dict) -> None:
    (report_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def test_synthetic_detection_outcome_scorecard_calibration_and_cockpit_chain(tmp_path: Path) -> None:
    detection = {
        "date": "2026-08-21", "detection_id": "pd-e2e", "symbol": "SPY",
        "pattern_id": "ict_cisd_universal_model", "setup_family": "ict_cisd_universal_model",
        "family": "liquidity_delivery", "direction": "bullish", "trigger_timeframe": "5m",
        "trigger_bar_ts": "2026-08-21T14:30:00Z", "grade": "A", "probability": 0.62,
        "execution_enabled": False, "can_submit_orders": False,
    }
    outcome = {
        **detection, "resolved_at": "2026-08-21T16:00:00Z", "outcome_r": 1.5,
        "regime": "trend", "execution_enabled": False, "can_submit_orders": False,
    }
    truth = {
        "date": "2026-08-21", "generated_at": "2026-08-24T20:59:00Z",
        "ground_truth_status": "qualified", "metrics_qualified": True,
        "pattern_annotation_qualified": False, "producer_healthy": True,
        "moves": [{
            "move_id": "SPY:5m:2026-08-21T14:30:00Z", "date": "2026-08-21",
            "symbol": "SPY", "timeframe": "5m", "trigger_bar_ts": "2026-08-21T14:30:00Z",
            "direction": "bullish", "label": 1, "excluded": False,
        }],
    }
    radar = [{
        "date": "2026-08-21", "generated_at": "2026-08-21T14:30:00Z",
        "all_discovered_symbols": ["SPY"],
        "ranked_candidates": [{"symbol": "SPY", "direction": "bullish"}],
    }]
    scorecard = build_scorecard(
        truth, radar, pattern_grader_rows=[detection], pattern_outcome_rows=[outcome]
    )
    rolling = build_rolling([scorecard])
    calibration = build_calibration([outcome], now=NOW)

    assert scorecard["pattern_coverage"]["opportunity_coverage"]["recall"] == 1.0
    assert scorecard["pattern_coverage"]["per_family"][0]["outcome_quality"]["average_r"] == 1.5
    assert calibration["eligible_outcomes"] == 1
    assert calibration["buckets"][0]["probability"]["status"] == "not_calibrated"

    _write(tmp_path, "pattern-grader-grades.json", {
        "generated_at": "2026-08-24T20:59:00Z",
        "scan_reconciliation": {"denominator_reconciled": True, "producer_failure_count": 0},
    })
    _write(tmp_path, "intraday-opportunity-radar.json", {
        "generated_at": "2026-08-24T20:59:20Z",
        "operational_health": "ok",
        "errors": [],
        "coverage": {
            "snapshot_coverage_pct": 99.0,
            "symbols_evaluated": 160,
            "symbols_with_5m_bars": 155,
            "reserved_liquid_core": [
                "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "AMZN",
                "META", "GOOGL", "TSLA", "AMD", "AVGO", "MSTR", "COIN",
            ],
        },
    })
    _write(tmp_path, "live-opportunity-engine.json", {
        "generated_at": "2026-08-24T20:59:40Z",
        "stream_status": "connected_hybrid",
        "candidate_count": 1,
        "stream_coverage": {"mandatory_core_missing": []},
    })
    _write(tmp_path, "move-ground-truth-summary.json", truth)
    _write(tmp_path, "detection-scorecard-rolling.json", rolling)
    _write(tmp_path, "grade-probability-calibration.json", calibration)
    _write(tmp_path, "daily-aplus-review.json", {
        "timestamp": "2026-08-24T20:59:00Z", "review_status": "complete",
        "summary": {"overall_review_coverage_pct": 100.0}, "source_inventory": [],
    })
    _write(tmp_path, "options-feed-qualification.json", {
        "generated_at": "2026-08-24T20:59:58Z",
        "status": "manual_execution_reference_available",
        "summary": {"manual_execution_qualified": 1},
    })
    _write(tmp_path, "options-reference-refresh.json", {
        "generated_at": "2026-08-24T20:59:50Z", "captured_count": 10,
    })
    _write(tmp_path, "manual-execution-quality.json", {
        "generated_at": "2026-08-24T20:59:00Z", "status": "awaiting_observations",
    })
    _write(tmp_path, "broker-fill-observer.json", {
        "generated_at": "2026-08-24T20:59:00Z", "status": "no_fills",
    })

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["schema_version"] == 12
    assert cockpit["system_readiness"]["build"]["percent"] == 100.0
    assert cockpit["system_readiness"]["runtime"]["percent"] == 100.0, [
        gate for gate in cockpit["system_readiness"]["runtime"]["gates"] if not gate["ready"]
    ]
    assert cockpit["system_readiness"]["ready_for_manual_review"] is True
    assert cockpit["system_readiness"]["probability_claims_qualified"] is False
    assert cockpit["discovery"]["scorecard_rolling"]["pattern_coverage"]["opportunity_coverage"]["recall"] == 1.0
    assert cockpit["authority"]["execution_enabled"] is False
    assert cockpit["authority"]["can_submit_orders"] is False
