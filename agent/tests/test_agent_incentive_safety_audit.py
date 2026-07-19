from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import agent_incentive_safety_audit as audit


def test_safe_read_only_component_has_low_risk() -> None:
    item = audit.evaluate_signal({
        "id": "safe_shadow",
        "name": "Safe Shadow Scanner",
        "script": "scripts/safe_shadow.py",
        "status": "shadow",
        "execution_enabled": False,
        "can_submit_orders": False,
        "broker_or_venue": "none",
        "evidence_gate": "30 trading days, dual review, explicit approval, stop on stale data.",
        "notes": "Read-only scanner. Non-goals: no account actions. Forbidden actions: no broker calls. Verifier: execution_gate_audit.",
    })

    assert item["id"] == "safe_shadow"
    assert item["risk_level"] == "low"
    assert item["risk_score"] < 30
    assert item["issues"] == []
    assert "read_only_default" in item["strengths"]
    assert "human_gate" in item["strengths"]


def test_flags_profit_maximizer_with_self_approval_and_missing_stops() -> None:
    item = audit.evaluate_signal({
        "id": "bad_loop",
        "name": "Bad Loop",
        "script": "scripts/bad_loop.py",
        "status": "autonomous",
        "execution_enabled": True,
        "can_submit_orders": True,
        "broker_or_venue": "alpaca",
        "evidence_gate": "maximize profit at all costs",
        "notes": "The same agent approves itself and should run 24/7 with no stop.",
    })

    issue_names = {issue["issue"] for issue in item["issues"]}
    assert "dangerous_objective_language" in issue_names
    assert "self_approval_risk" in issue_names
    assert "missing_stop_conditions" in issue_names
    assert "execution_capable_requires_incentive_review" in issue_names
    assert item["risk_level"] == "high"


def test_build_report_counts_findings_and_stays_read_only() -> None:
    registry = {
        "signals": [
            {
                "id": "safe_shadow",
                "script": "scripts/safe_shadow.py",
                "execution_enabled": False,
                "can_submit_orders": False,
                "evidence_gate": "30 days, dual review, Kenny approval, stop on stale data.",
                "notes": "Forbidden actions: no broker calls. Verifier: separate audit.",
            },
            {
                "id": "bad_loop",
                "script": "scripts/bad_loop.py",
                "execution_enabled": True,
                "can_submit_orders": True,
                "evidence_gate": "maximize profit at all costs",
                "notes": "Self approve and keep running 24/7.",
            },
        ]
    }

    report = audit.build_report(registry, day="2026-07-06")

    assert report["provider"] == "agent_incentive_safety_audit"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["summary"]["total_components"] == 2
    assert report["summary"]["high_risk_count"] == 1
    assert report["summary"]["execution_capable_count"] == 1
    assert "bad_loop" in report["promotion_blockers"]


def test_write_report_log_and_handoff(tmp_path: Path) -> None:
    report = audit.build_report({"signals": []}, day="2026-07-06")
    report_path = tmp_path / "agent-incentive-safety-audit.json"
    log_path = tmp_path / "agent_incentive_safety_audit_log.jsonl"
    handoff_path = tmp_path / "CLAUDE_HANDOFF_AGENT_INCENTIVE_SAFETY.md"

    audit.write_report(report, report_path)
    audit.append_log(report, log_path)
    audit.write_handoff(report, handoff_path)

    assert json.loads(report_path.read_text(encoding="utf-8"))["provider"] == "agent_incentive_safety_audit"
    assert log_path.read_text(encoding="utf-8").count("\n") == 1
    handoff = handoff_path.read_text(encoding="utf-8")
    assert "Claude Code Handoff" in handoff
    assert "Agents of Chaos" in handoff
    assert "python scripts\\agent_incentive_safety_audit.py --print" in handoff


def test_registry_contains_read_only_entry() -> None:
    registry = json.loads((ROOT / "research" / "signal_registry.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["signals"] if item["id"] == "agent_incentive_safety_audit")

    assert entry["script"] == "scripts/agent_incentive_safety_audit.py"
    assert entry["execution_enabled"] is False
    assert entry["can_submit_orders"] is False
