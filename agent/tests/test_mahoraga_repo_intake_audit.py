from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import mahoraga_repo_intake_audit as audit


def test_build_report_is_read_only_and_blocks_execution_imports() -> None:
    report = audit.build_report(day="2026-07-06")

    assert report["provider"] == "mahoraga_repo_intake_audit"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["summary"]["selected_count"] >= 5
    assert "deploy_mahoraga_worker" in report["summary"]["rejected_actions"]
    assert "copy_alpaca_execution" in report["summary"]["rejected_actions"]
    assert all(item["imports_external_code"] is False for item in report["items"])


def test_actions_prioritize_architecture_and_staleness_exit() -> None:
    report = audit.build_report(day="2026-07-06")
    by_id = {item["idea_id"]: item for item in report["items"]}

    assert by_id["pluggable_strategy_contract"]["recommended_action"] == "adopt_design_pattern"
    assert by_id["staleness_exit_shadow"]["recommended_action"] == "convert_to_read_only_tool"
    assert by_id["social_sentiment_gatherers"]["recommended_action"] == "extend_existing_tool"
    assert by_id["alpaca_execution_worker"]["recommended_action"] == "reject_execution_import"
    assert by_id["position_size_pct_of_cash_25"]["recommended_action"] == "reject_risk_setting"
    assert by_id["staleness_exit_shadow"]["confidence_score"] > by_id["alpaca_execution_worker"]["confidence_score"]


def test_report_surfaces_local_upgrade_queue() -> None:
    report = audit.build_report(day="2026-07-06")
    queue = report["local_upgrade_queue"]

    assert queue[0]["idea_id"] in {"staleness_exit_shadow", "pluggable_strategy_contract"}
    assert all(item["execution_enabled"] is False for item in queue)
    assert any(item["next_local_tool"] == "flip_social_staleness_shadow" for item in queue)
    assert report["claude_handoff"]["next_task"]["id"] == "evaluate-mahoraga-staleness-exit"


def test_write_report_and_handoff(tmp_path: Path) -> None:
    report = audit.build_report(day="2026-07-06")
    report_path = tmp_path / "mahoraga-repo-intake-audit.json"
    handoff_path = tmp_path / "CLAUDE_HANDOFF_MAHORAGA_INTAKE.md"

    audit.write_report(report, report_path)
    audit.write_handoff(report, handoff_path)

    loaded = json.loads(report_path.read_text(encoding="utf-8"))
    handoff = handoff_path.read_text(encoding="utf-8")
    assert loaded["provider"] == "mahoraga_repo_intake_audit"
    assert "Claude Code Handoff" in handoff
    assert "Do not deploy MAHORAGA" in handoff
    assert "python scripts\\mahoraga_repo_intake_audit.py --print" in handoff


def test_registry_contains_read_only_entry() -> None:
    registry = json.loads((ROOT / "research" / "signal_registry.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["signals"] if item["id"] == "mahoraga_repo_intake_audit")

    assert entry["script"] == "scripts/mahoraga_repo_intake_audit.py"
    assert entry["execution_enabled"] is False
    assert entry["can_submit_orders"] is False
