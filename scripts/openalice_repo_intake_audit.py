#!/usr/bin/env python3
"""Read-only intake audit for TraderAlice/OpenAlice architecture ideas.

This does not install OpenAlice, connect brokers, import external code, launch
agent CLIs, or change bot settings. It turns useful workspace/issue/inbox ideas
into local governed upgrade candidates for Vibe-Trading.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
SOURCE_REPO = "https://github.com/TraderAlice/OpenAlice"
REPORT_PATH = REPORT_DIR / "openalice-repo-intake-audit.json"
LOG_PATH = ROOT / "data" / "openalice_repo_intake_audit_log.jsonl"
HANDOFF_PATH = ROOT / "CODEx_CLAUDE_COLLAB" / "CLAUDE_HANDOFF_OPENALICE_INTAKE_2026-07-06.md"

REJECTED_ACTIONS = [
    "connect_unified_trading_account",
    "copy_trading_as_git_execution",
    "run_openalice_desktop",
    "launch_agent_cli_scheduler",
    "import_agpl_code_into_repo",
]

SELECTED_IDEAS: list[dict[str, Any]] = [
    {
        "idea_id": "markdown_issue_board",
        "source_area": "Issue Board: markdown-backed work items with status, priority, schedule metadata",
        "bot_gap": "Our agent work is split across chat handoffs and reports; recurring research tasks need durable local issue files.",
        "improves": ["research_loop", "handoffs", "scheduled_review", "accountability"],
        "recommended_action": "adopt_design_pattern",
        "next_local_tool": "vibe_research_issue_board",
        "confidence_score": 94,
        "risk_score": 6,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Create local markdown issue templates under CODEx_CLAUDE_COLLAB/issues or KNOWLEDGE/issues. No OpenAlice code required.",
    },
    {
        "idea_id": "inbox_delivery_surface",
        "source_area": "Inbox: finished work delivered as durable reports",
        "bot_gap": "Dashboard and reports exist, but human-facing agent deliverables are scattered across handoff files and chat.",
        "improves": ["dashboard", "daily_review", "agent_status"],
        "recommended_action": "extend_existing_tool",
        "next_local_tool": "dashboard_agent_inbox_panel",
        "confidence_score": 88,
        "risk_score": 8,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Add an inbox section to the static dashboard reading Claude handoffs, nightly reports, and needs-review summaries.",
    },
    {
        "idea_id": "tracked_entity_memory_graph",
        "source_area": "Tracked entities: assets, sectors, topics, theses, people",
        "bot_gap": "We track signals and logs, but not a single durable memory graph for tickers/themes/people/theses.",
        "improves": ["memory", "research_context", "creator_watchlist_validation"],
        "recommended_action": "extend_existing_tool",
        "next_local_tool": "tracked_entity_registry",
        "confidence_score": 86,
        "risk_score": 10,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Build local JSON/markdown entity registry mapping tickers, catalysts, creators, scanners, and thesis state.",
    },
    {
        "idea_id": "workspace_automation_issues",
        "source_area": "Scheduled runs through self-describing issues",
        "bot_gap": "Task Scheduler runs scripts, but it does not explain why a task exists or where results should land.",
        "improves": ["scheduler", "loop_readiness", "auditability"],
        "recommended_action": "study_only",
        "next_local_tool": "scheduler_issue_metadata_note",
        "confidence_score": 76,
        "risk_score": 18,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Use as documentation pattern first. Do not launch agent CLI schedulers.",
    },
    {
        "idea_id": "trading_as_git_approval_pattern",
        "source_area": "Trading as Git: staged, committed, reviewed, approval-gated operations",
        "bot_gap": "We already require approval; staging proposed account actions as files could improve review clarity later.",
        "improves": ["execution_governance", "auditability", "human_approval"],
        "recommended_action": "study_only",
        "next_local_tool": "trade_proposal_packet_design",
        "confidence_score": 72,
        "risk_score": 28,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Study as an approval-packet design only. Do not copy execution plumbing or broker abstractions.",
    },
    {
        "idea_id": "market_tools_workspace",
        "source_area": "Market tools exposed through local CLIs/files",
        "bot_gap": "Our reports are strong, but a consistent local tool index would help Claude/Codex discover them.",
        "improves": ["tool_discovery", "agent_handoff", "dashboard"],
        "recommended_action": "extend_existing_tool",
        "next_local_tool": "vibe_market_tool_index",
        "confidence_score": 80,
        "risk_score": 14,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Generate an index of safe read-only scripts, reports, inputs, and expected outputs.",
    },
    {
        "idea_id": "unified_trading_account",
        "source_area": "Unified Trading Account beta account abstraction",
        "bot_gap": "None for now. Current execution surface is deliberately narrow.",
        "improves": [],
        "recommended_action": "reject_execution_import",
        "next_local_tool": "none",
        "confidence_score": 25,
        "risk_score": 92,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Reject. Broker abstractions are beta in OpenAlice and would widen execution risk.",
    },
    {
        "idea_id": "agent_cli_scheduler",
        "source_area": "Scheduled native agent CLI workspace runs",
        "bot_gap": "Interesting, but our current scheduler should run deterministic scripts, not autonomous coding sessions.",
        "improves": [],
        "recommended_action": "reject_autonomous_agent_scheduler",
        "next_local_tool": "none",
        "confidence_score": 30,
        "risk_score": 80,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Reject for now. We can hand off to Claude Code manually; unattended coding agents need stronger controls.",
    },
]


def _action_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        action = str(item["recommended_action"])
        counts[action] = counts.get(action, 0) + 1
    return counts


def _upgrade_queue(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {"adopt_design_pattern", "extend_existing_tool", "study_only"}
    queue = [
        item for item in items
        if item["recommended_action"] in allowed and int(item["confidence_score"]) > int(item["risk_score"])
    ]
    queue.sort(
        key=lambda item: (
            int(item["confidence_score"]) - int(item["risk_score"]),
            int(item["confidence_score"]),
        ),
        reverse=True,
    )
    return [
        {
            "idea_id": item["idea_id"],
            "recommended_action": item["recommended_action"],
            "next_local_tool": item["next_local_tool"],
            "confidence_score": item["confidence_score"],
            "risk_score": item["risk_score"],
            "execution_enabled": False,
        }
        for item in queue[:6]
    ]


def _next_task(queue: list[dict[str, Any]]) -> dict[str, str]:
    if queue and queue[0]["idea_id"] == "markdown_issue_board":
        return {
            "id": "build-vibe-research-issue-board",
            "title": "Build a local markdown issue board for recurring trading research",
            "instructions": "Design this as file-backed research governance only. No agent scheduler, no broker connection, no OpenAlice code import.",
        }
    return {
        "id": "evaluate-openalice-inbox",
        "title": "Evaluate dashboard inbox delivery surface",
        "instructions": "Extend the static dashboard only after confirming report paths and handoff files.",
    }


def build_report(day: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    items = sorted(
        SELECTED_IDEAS,
        key=lambda item: (
            int(item["confidence_score"]) - int(item["risk_score"]),
            int(item["confidence_score"]),
        ),
        reverse=True,
    )
    queue = _upgrade_queue(items)
    return {
        "provider": "openalice_repo_intake_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_repo": SOURCE_REPO,
        "summary": {
            "selected_count": len(items),
            "actions": _action_counts(items),
            "rejected_actions": REJECTED_ACTIONS,
            "top_candidate": queue[0]["idea_id"] if queue else None,
        },
        "items": items,
        "local_upgrade_queue": queue,
        "claude_handoff": {
            "next_task": _next_task(queue),
            "commands": [
                "python scripts\\openalice_repo_intake_audit.py --print",
                "python scripts\\execution_gate_audit.py --fail-on-issues --print",
                "python -m pytest agent\\tests\\test_openalice_repo_intake_audit.py -q",
            ],
        },
        "warnings": [
            "Read-only architecture intake. No OpenAlice code imported.",
            "Do not connect broker accounts or copy trading-account abstractions.",
            "Do not launch autonomous agent CLI schedulers.",
            "AGPL source requires care; use ideas, not code.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def write_handoff(report: dict[str, Any], path: Path = HANDOFF_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    task = report["claude_handoff"]["next_task"]
    lines = [
        "# Claude Code Handoff - OpenAlice Intake",
        "",
        f"Date: {report['date']}",
        f"Generated: {report['generated_at']}",
        "",
        "## Objective",
        "",
        "Evaluate OpenAlice-inspired workspace improvements without importing AGPL code, launching agent schedulers, or connecting broker accounts.",
        "",
        "## Next Task",
        "",
        f"- ID: {task['id']}",
        f"- Title: {task['title']}",
        f"- Instructions: {task['instructions']}",
        "",
        "## Top Local Upgrade Queue",
        "",
    ]
    for item in report["local_upgrade_queue"]:
        lines.append(
            f"- {item['idea_id']}: {item['recommended_action']} -> {item['next_local_tool']} "
            f"(confidence={item['confidence_score']}, risk={item['risk_score']})"
        )
    lines.extend([
        "",
        "## Hard Blocks",
        "",
        "- Do not connect broker accounts.",
        "- Do not copy Trading as Git execution plumbing.",
        "- Do not launch autonomous agent CLI schedulers.",
        "- Do not import AGPL code into this repo.",
        "",
        "## Commands",
        "",
        "```powershell",
    ])
    lines.extend(report["claude_handoff"]["commands"])
    lines.extend(["```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nOpenAlice Repo Intake Audit | read-only")
    print("=" * 88)
    print(f"selected={report['summary']['selected_count']} actions={report['summary']['actions']}")
    print(f"top_candidate={report['summary']['top_candidate']}")
    for item in report["local_upgrade_queue"]:
        print(
            f"{item['idea_id']:<32} action={item['recommended_action']:<22} "
            f"next={item['next_local_tool']:<32} confidence={item['confidence_score']} risk={item['risk_score']}"
        )
    print("Hard blocks: no broker accounts, no Trading-as-Git execution copy, no agent CLI scheduler.")
    print(f"JSON: {REPORT_PATH}")
    print(f"Handoff: {HANDOFF_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only intake audit for OpenAlice architecture ideas.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--handoff-path", type=Path, default=HANDOFF_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    report = build_report(day=args.date)
    if not args.no_write:
        write_report(report, args.report_path)
        append_log(report, args.log_path)
        write_handoff(report, args.handoff_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"OpenAlice repo intake audit wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
