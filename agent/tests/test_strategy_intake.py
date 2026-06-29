from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.strategy_intake import build_report, evaluate_item, load_queue, run_report


def _base_item(**overrides):
    item = {
        "id": "test-001",
        "source_platform": "web/quantifiedstrategies.com",
        "source_url": "https://example.com",
        "trader": "Rules Trader",
        "strategy_name": "Simple Daily Mean Reversion",
        "market": "QQQ",
        "timeframe": "daily",
        "entry_rules": "Buy next open when RSI(2) closes below 10 and close is above SMA(200).",
        "stop_loss_rules": "Exit after a close below SMA(200).",
        "take_profit_rules": "Exit when close is above prior day high.",
        "exit_rules": "Take profit rule or stop rule, whichever happens first.",
        "position_sizing": "100% notional in backtest; paper sizing reviewed later.",
        "session_rules": "Daily close signal, next regular-session open entry.",
        "ambiguities": ["Commission/slippage source assumptions need review."],
        "license_or_permission_notes": "Public strategy concept; no source code copied.",
        "pine_status": "not_started",
        "python_status": "not_started",
        "backtest_status": "pending",
        "decision": "pending",
        "rejection_reasons": [],
        "next_action": "Port to Python and run backtest.",
    }
    item.update(overrides)
    return item


def test_evaluate_item_promotes_clear_rules_to_ready_for_port() -> None:
    evaluation = evaluate_item(_base_item())

    assert evaluation.stage == "ready_for_port"
    assert evaluation.readiness_score >= 6
    assert "complete rule set" in evaluation.strengths
    assert "backtest pending" in evaluation.blockers


def test_evaluate_item_routes_scan_needed_repo_to_needs_scan() -> None:
    evaluation = evaluate_item(_base_item(
        source_platform="github",
        license_or_permission_notes="Check repo license.",
        pine_status="needs_scan",
    ))

    assert evaluation.stage == "needs_scan"
    assert "Pine source scan required" in evaluation.blockers
    assert "license or permission needs review" in evaluation.blockers


def test_build_report_summarizes_stage_counts() -> None:
    report = build_report([
        _base_item(id="ready"),
        _base_item(id="scan", source_platform="github", pine_status="needs_scan", license_or_permission_notes="Check repo license."),
        _base_item(id="reject", decision="rejected", rejection_reasons=["high drawdown"]),
    ])

    assert report["mode"] == "research_only"
    assert report["execution_enabled"] is False
    assert report["queue_count"] == 3
    assert report["stage_counts"]["ready_for_port"] == 1
    assert report["stage_counts"]["needs_scan"] == 1
    assert report["stage_counts"]["rejected"] == 1
    assert report["top_next_actions"]


def test_run_report_loads_queue_and_writes_json(tmp_path) -> None:
    queue = tmp_path / "strategy_queue.json"
    out = tmp_path / "report.json"
    queue.write_text(json.dumps([_base_item()]), encoding="utf-8")

    report = run_report(queue_path=queue, out=out)
    loaded = load_queue(queue)

    assert out.exists()
    assert len(loaded) == 1
    assert report["items"][0]["strategy_name"] == "Simple Daily Mean Reversion"
