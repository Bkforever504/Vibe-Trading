from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import trading_skills_intake_audit as intake


def test_build_report_only_includes_selected_skills() -> None:
    report = intake.build_report(day="2026-07-04")
    ids = [item["skill_id"] for item in report["items"]]

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert set(ids) == {
        "walk-forward-validation",
        "position-sizing",
        "options-pricing",
        "trade-journal",
    }
    assert "risk-management" not in ids


def test_actions_match_bot_improvement_filter() -> None:
    report = intake.build_report(day="2026-07-04")
    by_id = {item["skill_id"]: item for item in report["items"]}

    assert by_id["walk-forward-validation"]["recommended_action"] == "convert_to_read_only_tool"
    assert by_id["position-sizing"]["recommended_action"] == "convert_to_read_only_tool"
    assert by_id["options-pricing"]["recommended_action"] == "study_only"
    assert by_id["trade-journal"]["recommended_action"] == "extend_existing_tool"
    assert by_id["options-pricing"]["upstream_status"] == "stub"
    assert by_id["walk-forward-validation"]["confidence_score"] > by_id["options-pricing"]["confidence_score"]


def test_log_report_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "intake.jsonl"
    report = intake.build_report(day="2026-07-04")

    intake.append_log(report, log_path=path)

    loaded = json.loads(path.read_text(encoding="utf-8").strip())
    assert loaded["provider"] == "trading_skills_intake_audit"
    assert loaded["summary"]["selected_count"] == 4


def test_registry_contains_read_only_intake_entry() -> None:
    registry = json.loads((ROOT / "research" / "signal_registry.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["signals"] if item["id"] == "trading_skills_intake_audit")

    assert entry["script"] == "scripts/trading_skills_intake_audit.py"
    assert entry["runner"] == "scripts/run_trading_skills_intake_audit.ps1"
    assert entry["execution_enabled"] is False
    assert entry["can_submit_orders"] is False
