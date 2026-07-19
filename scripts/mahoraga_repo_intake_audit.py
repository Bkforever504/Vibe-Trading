#!/usr/bin/env python3
"""Read-only intake audit for ygwyg/MAHORAGA architecture ideas.

This does not clone MAHORAGA, deploy Workers, import TypeScript, call Alpaca, or
change bot settings. It converts useful upstream concepts into local,
governed upgrade candidates for the Vibe-Trading stack.
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
SOURCE_REPO = "https://github.com/ygwyg/MAHORAGA"
REPORT_PATH = REPORT_DIR / "mahoraga-repo-intake-audit.json"
LOG_PATH = ROOT / "data" / "mahoraga_repo_intake_audit_log.jsonl"
HANDOFF_PATH = ROOT / "CODEx_CLAUDE_COLLAB" / "CLAUDE_HANDOFF_MAHORAGA_INTAKE_2026-07-06.md"

REJECTED_ACTIONS = [
    "deploy_mahoraga_worker",
    "copy_alpaca_execution",
    "enable_24_7_autonomous_trading",
    "import_default_25pct_sizing",
    "route_social_sentiment_to_orders",
]

SELECTED_IDEAS: list[dict[str, Any]] = [
    {
        "idea_id": "staleness_exit_shadow",
        "source_area": "default strategy exit/staleness rules",
        "bot_gap": "Flip Bot needs explicit evidence when social/momentum confirmation fades after entry.",
        "improves": ["exit_intelligence", "profit_capture", "same_day_reentry_filter"],
        "recommended_action": "convert_to_read_only_tool",
        "next_local_tool": "flip_social_staleness_shadow",
        "confidence_score": 90,
        "risk_score": 10,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Build a local shadow report that compares open/closed Flip trades with decaying social heat, creator confirmation, and market-force fade. Do not make it an exit gate until repeated evidence exists.",
    },
    {
        "idea_id": "pluggable_strategy_contract",
        "source_area": "strategy harness: gatherers, prompts, entry rules, exit rules, config",
        "bot_gap": "Our scanners are numerous but lack one common contract for idea intake -> score -> validate -> shadow -> govern.",
        "improves": ["architecture", "scanner_consistency", "promotion_governance"],
        "recommended_action": "adopt_design_pattern",
        "next_local_tool": "strategy_module_contract_doc",
        "confidence_score": 88,
        "risk_score": 8,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Document a Python-side contract for scanner modules. Keep it report-only; do not refactor working scanners yet.",
    },
    {
        "idea_id": "social_sentiment_gatherers",
        "source_area": "StockTwits/Reddit/Twitter confirmation gatherers",
        "bot_gap": "Creator/social observations are manual and need structured source freshness, volume, sentiment, and confirmation fields.",
        "improves": ["social_intake", "creator_watchlist_validation", "cheap_asymmetry_context"],
        "recommended_action": "extend_existing_tool",
        "next_local_tool": "extend_public_social_intake_schema",
        "confidence_score": 82,
        "risk_score": 18,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Extend existing public_social_intake/creator_watchlist data shape. Social data remains discovery context, never direct order input.",
    },
    {
        "idea_id": "policy_wrapped_execution_design",
        "source_area": "policy-broker trade validation wrapper",
        "bot_gap": "Execution-capable bots already have guards, but policy checks should be easy to audit in one place.",
        "improves": ["execution_safety", "guard_observability", "auditability"],
        "recommended_action": "study_only",
        "next_local_tool": "execution_policy_contract_review",
        "confidence_score": 74,
        "risk_score": 22,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Study the separation pattern only. Our shared execution_guard remains source of truth.",
    },
    {
        "idea_id": "dashboard_status_logs_api",
        "source_area": "agent status/log endpoints and dashboard",
        "bot_gap": "The local dashboard needs clearer loop state, bot health, and recent decision logs.",
        "improves": ["dashboard", "observability", "daily_review"],
        "recommended_action": "extend_existing_tool",
        "next_local_tool": "dashboard_loop_state_panel",
        "confidence_score": 78,
        "risk_score": 12,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Use the status/log idea in our static dashboard. Avoid adding authenticated web control endpoints.",
    },
    {
        "idea_id": "cloudflare_durable_state",
        "source_area": "Cloudflare Durable Object persistent state",
        "bot_gap": "Our current local state is file-based; durable remote state could help later but adds infra and secret surface.",
        "improves": ["state_durability", "remote_observability"],
        "recommended_action": "study_only",
        "next_local_tool": "state_backend_tradeoff_note",
        "confidence_score": 55,
        "risk_score": 35,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Not a near-term change. Local JSON/JSONL state is simpler and safer today.",
    },
    {
        "idea_id": "alpaca_execution_worker",
        "source_area": "Cloudflare Worker Alpaca execution endpoints",
        "bot_gap": "None. We already have controlled paper execution bots with local guards.",
        "improves": [],
        "recommended_action": "reject_execution_import",
        "next_local_tool": "none",
        "confidence_score": 20,
        "risk_score": 95,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Reject. Do not deploy MAHORAGA or copy broker execution code. It increases live-trading surface area.",
    },
    {
        "idea_id": "position_size_pct_of_cash_25",
        "source_area": "agent-config.example.json",
        "bot_gap": "None. This conflicts with Vibe-Trading risk discipline.",
        "improves": [],
        "recommended_action": "reject_risk_setting",
        "next_local_tool": "none",
        "confidence_score": 10,
        "risk_score": 90,
        "imports_external_code": False,
        "execution_enabled": False,
        "notes": "Reject. MAHORAGA example uses 25pct of cash; our Flip Bot risk fix intentionally moved to 2pct and max 5 contracts.",
    },
]


def _action_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        action = str(item["recommended_action"])
        counts[action] = counts.get(action, 0) + 1
    return counts


def _upgrade_queue(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {
        "adopt_design_pattern",
        "convert_to_read_only_tool",
        "extend_existing_tool",
        "study_only",
    }
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
    staleness = next((item for item in queue if item["idea_id"] == "staleness_exit_shadow"), None)
    if staleness:
        return {
            "id": "evaluate-mahoraga-staleness-exit",
            "title": "Evaluate social/momentum staleness as a Flip Bot shadow exit lesson",
            "instructions": "Build only if it remains read-only and compares social heat decay against Flip Bot postmortems and capture gaps.",
        }
    return {
        "id": "document-mahoraga-strategy-contract",
        "title": "Document the scanner strategy contract",
        "instructions": "Write the gather -> score -> validate -> shadow -> govern contract before refactoring any scanner.",
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
        "provider": "mahoraga_repo_intake_audit",
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
                "python scripts\\mahoraga_repo_intake_audit.py --print",
                "python scripts\\execution_gate_audit.py --fail-on-issues --print",
                "python -m pytest agent\\tests\\test_mahoraga_repo_intake_audit.py -q",
            ],
        },
        "warnings": [
            "Read-only architecture intake. No external code imported.",
            "Do not deploy MAHORAGA or copy Alpaca execution endpoints.",
            "Social sentiment is discovery context only and must not route directly to orders.",
            "Reject MAHORAGA's example 25pct cash sizing for this stack.",
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
        "# Claude Code Handoff - MAHORAGA Intake",
        "",
        f"Date: {report['date']}",
        f"Generated: {report['generated_at']}",
        "",
        "## Objective",
        "",
        "Evaluate MAHORAGA-inspired architecture improvements without importing external code, deploying Workers, or touching broker execution.",
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
        "- Do not deploy MAHORAGA.",
        "- Do not copy Alpaca execution endpoints.",
        "- Do not route social sentiment directly to orders.",
        "- Do not adopt 25pct cash sizing.",
        "",
        "## Commands",
        "",
        "```powershell",
    ])
    lines.extend(report["claude_handoff"]["commands"])
    lines.extend([
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nMAHORAGA Repo Intake Audit | read-only")
    print("=" * 88)
    print(f"selected={report['summary']['selected_count']} actions={report['summary']['actions']}")
    print(f"top_candidate={report['summary']['top_candidate']}")
    for item in report["local_upgrade_queue"]:
        print(
            f"{item['idea_id']:<34} action={item['recommended_action']:<26} "
            f"next={item['next_local_tool']:<32} confidence={item['confidence_score']} risk={item['risk_score']}"
        )
    print("Hard blocks: do not deploy MAHORAGA, copy Alpaca execution, or adopt 25pct sizing.")
    print(f"JSON: {REPORT_PATH}")
    print(f"Handoff: {HANDOFF_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only intake audit for MAHORAGA architecture ideas.")
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
        print(f"MAHORAGA repo intake audit wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
