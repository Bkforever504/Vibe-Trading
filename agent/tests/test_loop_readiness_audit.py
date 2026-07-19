from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import loop_readiness_audit as audit


def _registry(signals: list[dict]) -> dict:
    return {
        "version": "test",
        "policy": {"execution_change_rule": "approval required"},
        "signals": signals,
    }


def test_classifies_report_only_loop_as_l1() -> None:
    signal = {
        "id": "nightly_alpha_factory",
        "name": "Nightly Alpha Factory",
        "script": "scripts/nightly_alpha_factory.py",
        "runner": "scripts/run_nightly_alpha_factory.ps1",
        "scheduled_tasks": [],
        "log_path": "data/nightly_alpha_factory_log.jsonl",
        "status": "governance",
        "execution_enabled": False,
        "can_submit_orders": False,
        "evidence_gate": "Read-only morning alpha factory. No promotion without explicit approval.",
        "notes": "Builder cannot approve its own signal. Writes Claude handoff.",
    }

    result = audit.score_signal(signal)

    assert result["loop_level"] == "L1"
    assert result["readiness_score"] >= 60
    assert result["execution_enabled"] is False
    assert "maker_checker_split" in result["strengths"]


def test_execution_capable_bot_is_capped_without_human_gate() -> None:
    signal = {
        "id": "flip_bot",
        "name": "Flip Bot",
        "script": "strategies/flip_bot.py",
        "runner": "scripts/run_flip_bot_entry.ps1",
        "scheduled_tasks": ["Flip-Bot-Entry"],
        "log_path": "~/.vibe-trading/flip-trades.json",
        "status": "execution_capable_paper",
        "execution_enabled": True,
        "can_submit_orders": True,
        "evidence_gate": "Live requires explicit user approval.",
        "notes": "Known execution bot. Must pass execution guard.",
    }

    result = audit.score_signal(signal)

    assert result["loop_level"] == "L2"
    assert "execution_capable_requires_human_gate" in result["cautions"]
    assert result["can_submit_orders"] is True


def test_build_report_summarizes_levels_and_keeps_read_only(tmp_path: Path) -> None:
    registry = _registry([
        {
            "id": "nightly_alpha_factory",
            "name": "Nightly Alpha Factory",
            "script": "scripts/nightly_alpha_factory.py",
            "runner": "scripts/run_nightly_alpha_factory.ps1",
            "scheduled_tasks": [],
            "log_path": "data/nightly_alpha_factory_log.jsonl",
            "status": "governance",
            "execution_enabled": False,
            "can_submit_orders": False,
            "evidence_gate": "Read-only handoff. No promotion without dual review and explicit approval.",
            "notes": "Builder cannot approve its own signal.",
        },
        {
            "id": "creator_watchlist_runner_scanner",
            "name": "Creator Watchlist Runner Scanner",
            "script": "scripts/creator_watchlist_runner_scanner.py",
            "runner": "scripts/run_creator_watchlist_runner_scanner.ps1",
            "scheduled_tasks": [],
            "log_path": "data/creator_watchlist_runner_log.jsonl",
            "status": "shadow_review",
            "execution_enabled": False,
            "can_submit_orders": False,
            "evidence_gate": "Read-only creator validation. No ticker can influence execution.",
            "notes": "Screenshots are discovery prompts only.",
        },
    ])

    report = audit.build_report(registry=registry, day="2026-07-06")

    assert report["provider"] == "loop_readiness_audit"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["summary"]["by_level"]["L1"] == 2
    assert report["summary"]["unattended_ready_count"] == 0
    assert report["claude_handoff"]["next_task"]["id"] == "review-lowest-loop-readiness"


def test_write_loop_doc_and_handoff_include_operating_rules(tmp_path: Path) -> None:
    report = {
        "date": "2026-07-06",
        "generated_at": "2026-07-07T04:00:00Z",
        "summary": {"total_loops": 2, "by_level": {"L1": 2}, "unattended_ready_count": 0},
        "claude_handoff": {
            "next_task": {
                "id": "review-lowest-loop-readiness",
                "title": "Review weakest loop readiness item",
                "instructions": "Improve documentation only.",
            }
        },
        "items": [{"id": "nightly_alpha_factory", "loop_level": "L1", "readiness_score": 70}],
    }
    loop_path = tmp_path / "LOOP.md"
    handoff_path = tmp_path / "CLAUDE_HANDOFF_LOOP_READINESS.md"

    audit.write_loop_doc(report, loop_path)
    audit.write_handoff(report, handoff_path)

    loop_text = loop_path.read_text(encoding="utf-8")
    handoff_text = handoff_path.read_text(encoding="utf-8")
    assert "Loop Operating System" in loop_text
    assert "L1 - Report Only" in loop_text
    assert "maker/checker" in loop_text
    assert "Claude Code Handoff" in handoff_text
    assert "python scripts\\loop_readiness_audit.py --print" in handoff_text


def test_write_report_round_trips_json(tmp_path: Path) -> None:
    path = tmp_path / "loop-readiness-audit.json"
    report = {"provider": "loop_readiness_audit", "execution_enabled": False}

    audit.write_report(report, path)

    assert json.loads(path.read_text(encoding="utf-8")) == report
