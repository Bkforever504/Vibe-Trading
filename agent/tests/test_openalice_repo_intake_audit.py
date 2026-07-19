from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import openalice_repo_intake_audit as audit


def test_build_report_is_read_only_and_rejects_broker_execution() -> None:
    report = audit.build_report(day="2026-07-06")

    assert report["provider"] == "openalice_repo_intake_audit"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["summary"]["selected_count"] >= 6
    assert "connect_unified_trading_account" in report["summary"]["rejected_actions"]
    assert "copy_trading_as_git_execution" in report["summary"]["rejected_actions"]
    assert all(item["imports_external_code"] is False for item in report["items"])


def test_actions_prioritize_workspace_issues_inbox_and_trading_as_git_pattern() -> None:
    report = audit.build_report(day="2026-07-06")
    by_id = {item["idea_id"]: item for item in report["items"]}

    assert by_id["markdown_issue_board"]["recommended_action"] == "adopt_design_pattern"
    assert by_id["tracked_entity_memory_graph"]["recommended_action"] == "extend_existing_tool"
    assert by_id["inbox_delivery_surface"]["recommended_action"] == "extend_existing_tool"
    assert by_id["trading_as_git_approval_pattern"]["recommended_action"] == "study_only"
    assert by_id["unified_trading_account"]["recommended_action"] == "reject_execution_import"
    assert by_id["markdown_issue_board"]["confidence_score"] > by_id["unified_trading_account"]["confidence_score"]


def test_report_surfaces_local_upgrade_queue() -> None:
    report = audit.build_report(day="2026-07-06")
    queue = report["local_upgrade_queue"]

    assert queue[0]["idea_id"] == "markdown_issue_board"
    assert all(item["execution_enabled"] is False for item in queue)
    assert any(item["next_local_tool"] == "vibe_research_issue_board" for item in queue)
    assert report["claude_handoff"]["next_task"]["id"] == "build-vibe-research-issue-board"


def test_write_report_and_handoff(tmp_path: Path) -> None:
    report = audit.build_report(day="2026-07-06")
    report_path = tmp_path / "openalice-repo-intake-audit.json"
    handoff_path = tmp_path / "CLAUDE_HANDOFF_OPENALICE_INTAKE.md"

    audit.write_report(report, report_path)
    audit.write_handoff(report, handoff_path)

    loaded = json.loads(report_path.read_text(encoding="utf-8"))
    handoff = handoff_path.read_text(encoding="utf-8")
    assert loaded["provider"] == "openalice_repo_intake_audit"
    assert "Claude Code Handoff" in handoff
    assert "Do not connect broker accounts" in handoff
    assert "python scripts\\openalice_repo_intake_audit.py --print" in handoff


def test_registry_contains_read_only_entry() -> None:
    registry = json.loads((ROOT / "research" / "signal_registry.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["signals"] if item["id"] == "openalice_repo_intake_audit")

    assert entry["script"] == "scripts/openalice_repo_intake_audit.py"
    assert entry["execution_enabled"] is False
    assert entry["can_submit_orders"] is False
