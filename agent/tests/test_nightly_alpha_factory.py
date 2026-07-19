from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import nightly_alpha_factory as factory


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_report_creates_read_only_six_agent_pipeline(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write(reports / "cheap-asymmetry-scanner.json", {
        "date": "2026-07-06",
        "candidate_count": 2,
        "summary": {"goal_match_count": 0},
        "top_candidates": [
            {"symbol": "AAPL", "best_return_pct": 538.71, "goal_match": False, "cost_at_open": 31.0},
            {"symbol": "META", "best_return_pct": 243.48, "goal_match": False, "cost_at_open": 23.0},
        ],
    })
    _write(reports / "creator-watchlist-runner-scanner.json", {
        "summary": {"symbol_count": 34, "runner_count": 4, "cheap_asymmetry_count": 2},
        "watchlist_results": [
            {"symbol": "AAPL", "verdict": "strong_runner_confirmed", "best_return_pct": 538.71},
            {"symbol": "HIMS", "verdict": "needs_shadow_evidence", "best_return_pct": 0},
        ],
    })
    _write(reports / "flip-bot-learning-report.json", {
        "actual": {"closed_count": 2, "net_pnl": -175.0},
        "lessons": [{"type": "capture_gap", "severity": "high", "symbol": "SPY"}],
    })
    _write(reports / "execution-gate-audit.json", {"passed": True, "issue_count": 0, "warning_count": 1})
    _write(reports / "strategy-leak-audit.json", {"summary": {"critical": 0}, "passed": True})
    _write(reports / "crowded-positioning-scanner.json", {
        "summary": {"crowded_side": "none", "crowding_score": 0},
        "flip_bot_context": {"posture": "normal"},
    })
    _write(reports / "loop-readiness-audit.json", {
        "summary": {"total_loops": 78, "by_level": {"L0": 0, "L1": 70, "L2": 8, "L3": 0}, "unattended_ready_count": 0},
        "claude_handoff": {"next_task": {"id": "review-lowest-loop-readiness"}},
    })
    _write(reports / "mahoraga-repo-intake-audit.json", {
        "summary": {"top_candidate": "staleness_exit_shadow"},
        "local_upgrade_queue": [
            {"idea_id": "staleness_exit_shadow", "next_local_tool": "flip_social_staleness_shadow", "recommended_action": "convert_to_read_only_tool"}
        ],
    })
    _write(reports / "openalice-repo-intake-audit.json", {
        "summary": {"top_candidate": "markdown_issue_board"},
        "local_upgrade_queue": [
            {"idea_id": "markdown_issue_board", "next_local_tool": "vibe_research_issue_board", "recommended_action": "adopt_design_pattern"}
        ],
    })
    _write(reports / "agent-incentive-safety-audit.json", {
        "passed": False,
        "summary": {"total_components": 81, "issue_count": 3, "high_risk_count": 1},
        "promotion_blockers": ["bad_loop"],
    })

    report = factory.build_report(day="2026-07-06", report_dir=reports)

    assert report["provider"] == "nightly_alpha_factory"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["governance"]["builder_cannot_approve_itself"] is True
    assert [agent["id"] for agent in report["agents"]] == [
        "idea_intake_agent",
        "feature_builder_agent",
        "backtest_replay_agent",
        "overfit_killer_agent",
        "regime_validator_agent",
        "governance_chair_agent",
    ]
    assert report["idea_intake"]["cheap_asymmetry_candidates"] == 2
    assert report["opportunity_queue"][0]["symbol"] == "AAPL"
    assert report["promotion_summary"]["promotion_ready_count"] == 0
    assert report["claude_handoff"]["next_task"]["id"] == "monitor-cheap-asymmetry"
    assert report["loop_readiness"]["by_level"]["L1"] == 70
    assert report["loop_readiness"]["unattended_ready_count"] == 0
    assert report["external_repo_intake"]["mahoraga_top_candidate"] == "staleness_exit_shadow"
    assert report["external_repo_intake"]["openalice_top_candidate"] == "markdown_issue_board"
    assert report["incentive_safety"]["issue_count"] == 3
    assert "incentive_safety_findings" in report["governance"]["blockers"]


def test_governance_blocks_promotion_when_audits_fail(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write(reports / "cheap-asymmetry-scanner.json", {
        "candidate_count": 1,
        "summary": {"goal_match_count": 1},
        "top_candidates": [{"symbol": "SPY", "goal_match": True, "best_return_pct": 700}],
    })
    _write(reports / "execution-gate-audit.json", {"passed": False, "issue_count": 1, "warning_count": 0})

    report = factory.build_report(day="2026-07-06", report_dir=reports)

    assert report["promotion_summary"]["promotion_ready_count"] == 0
    assert "execution_audit_failed" in report["governance"]["blockers"]
    assert report["claude_handoff"]["next_task"]["id"] == "fix-execution-audit-first"


def test_write_handoff_includes_claude_code_commands(tmp_path: Path) -> None:
    report = {
        "date": "2026-07-06",
        "generated_at": "2026-07-07T03:00:00Z",
        "headline": "2 ideas observed, 0 promoted.",
        "execution_enabled": False,
        "can_submit_orders": False,
        "governance": {
            "builder_cannot_approve_itself": True,
            "blockers": [],
            "forbidden_actions": ["Do not enable live trading."],
        },
        "claude_handoff": {
            "next_task": {
                "id": "monitor-cheap-asymmetry",
                "title": "Keep cheap asymmetry under observation",
                "instructions": "Collect another day of evidence.",
            }
        },
        "opportunity_queue": [{"symbol": "AAPL", "reason": "cheap_asymmetry"}],
        "agents": [],
    }
    path = tmp_path / "CLAUDE_HANDOFF_NIGHTLY_ALPHA_FACTORY.md"

    factory.write_handoff(report, path)

    text = path.read_text(encoding="utf-8")
    assert "Claude Code Handoff" in text
    assert "python scripts\\nightly_alpha_factory.py --print" in text
    assert "The builder cannot approve its own signal" in text
    assert "Do not enable live trading." in text


def test_write_report_round_trips_json(tmp_path: Path) -> None:
    path = tmp_path / "nightly-alpha-factory.json"
    report = {"date": "2026-07-06", "execution_enabled": False}

    factory.write_report(report, path)

    assert json.loads(path.read_text(encoding="utf-8")) == report
