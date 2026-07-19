#!/usr/bin/env python3
"""Score Vibe-Trading loops against loop-engineering readiness rules.

This is governance only. It reads the signal registry, assigns L0-L3 readiness
levels, writes a report, and produces a Claude Code handoff for review. It does
not schedule, trade, promote, or change risk settings.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REGISTRY_PATH = ROOT / "research" / "signal_registry.json"
REPORT_PATH = REPORT_DIR / "loop-readiness-audit.json"
LOG_PATH = ROOT / "data" / "loop_readiness_audit_log.jsonl"
LOOP_DOC_PATH = ROOT / "LOOP.md"
HANDOFF_PATH = ROOT / "CODEx_CLAUDE_COLLAB" / "CLAUDE_HANDOFF_LOOP_READINESS_2026-07-06.md"

LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text(signal: dict[str, Any]) -> str:
    return " ".join(
        str(signal.get(key) or "")
        for key in ("id", "name", "status", "evidence_gate", "notes", "feeds")
    ).lower()


def _has_value(signal: dict[str, Any], key: str) -> bool:
    value = signal.get(key)
    if isinstance(value, list):
        return bool(value)
    return bool(str(value or "").strip())


def _score_level(score: int, *, can_submit: bool, scheduled: bool, has_checker: bool, has_human_gate: bool) -> str:
    if can_submit:
        return "L2" if has_human_gate else "L1"
    if score < 35:
        return "L0"
    if score < 75:
        return "L1"
    if scheduled and has_checker and has_human_gate:
        return "L2"
    return "L1"


def score_signal(signal: dict[str, Any]) -> dict[str, Any]:
    text = _text(signal)
    can_submit = bool(signal.get("can_submit_orders"))
    execution_enabled = bool(signal.get("execution_enabled"))
    scheduled = bool(signal.get("scheduled_tasks"))

    has_goal = _has_value(signal, "evidence_gate")
    has_scope = _has_value(signal, "script")
    has_runner = _has_value(signal, "runner")
    has_log = _has_value(signal, "log_path")
    has_human_gate = any(term in text for term in ("explicit", "approval", "kenny", "manual"))
    has_checker = any(term in text for term in ("audit", "dual", "review", "builder cannot", "cannot approve", "execution_guard", "guard"))
    read_only_claim = any(term in text for term in ("read-only", "read only", "context only", "shadow", "no orders"))

    score = 0
    strengths: list[str] = []
    cautions: list[str] = []

    if has_goal:
        score += 15
        strengths.append("explicit_goal_or_gate")
    else:
        cautions.append("missing_evidence_gate")
    if has_scope:
        score += 10
        strengths.append("watched_scope")
    else:
        cautions.append("missing_script_scope")
    if has_runner:
        score += 10
        strengths.append("runner_documented")
    else:
        cautions.append("missing_runner")
    if has_log:
        score += 15
        strengths.append("state_or_run_log")
    else:
        cautions.append("missing_state_or_run_log")
    if scheduled:
        score += 10
        strengths.append("cadence_documented")
    else:
        cautions.append("manual_or_unscheduled")
    if has_checker:
        score += 15
        strengths.append("maker_checker_split")
    else:
        cautions.append("missing_maker_checker_split")
    if has_human_gate:
        score += 15
        strengths.append("human_gate")
    else:
        cautions.append("missing_human_gate")
    if read_only_claim and not can_submit:
        score += 10
        strengths.append("report_only_default")
    if can_submit:
        cautions.append("execution_capable_requires_human_gate")
    if execution_enabled and not can_submit:
        cautions.append("execution_enabled_without_order_capability")

    score = min(score, 100)
    level = _score_level(
        score,
        can_submit=can_submit,
        scheduled=scheduled,
        has_checker=has_checker,
        has_human_gate=has_human_gate,
    )
    return {
        "id": signal.get("id"),
        "name": signal.get("name"),
        "status": signal.get("status"),
        "loop_level": level,
        "readiness_score": score,
        "execution_enabled": execution_enabled,
        "can_submit_orders": can_submit,
        "scheduled": scheduled,
        "strengths": strengths,
        "cautions": cautions,
        "next_step": _next_step(level, cautions),
    }


def _next_step(level: str, cautions: list[str]) -> str:
    if "missing_maker_checker_split" in cautions:
        return "Add explicit maker/checker or dual-review language before any assisted action."
    if "missing_state_or_run_log" in cautions:
        return "Add durable state/run-log path before scheduling."
    if level == "L0":
        return "Document purpose, non-goals, scope, state, and human gate."
    if level == "L1":
        return "Keep report-only; improve verification and state before assisted fixes."
    if level == "L2":
        return "Assisted only; human approval remains required for execution/risk changes."
    return "Unattended status is not allowed for trading execution loops."


def _next_task(items: list[dict[str, Any]]) -> dict[str, str]:
    sorted_items = sorted(items, key=lambda item: (item["readiness_score"], item["id"] or ""))
    target = sorted_items[0] if sorted_items else {"id": "none", "next_step": "No registered loops found."}
    return {
        "id": "review-lowest-loop-readiness",
        "title": f"Review loop readiness for {target.get('id')}",
        "instructions": str(target.get("next_step") or "Improve documentation and verification only."),
    }


def build_report(registry: dict[str, Any] | None = None, day: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    registry = registry or _read_json(REGISTRY_PATH)
    signals = registry.get("signals") if isinstance(registry.get("signals"), list) else []
    items = [score_signal(signal) for signal in signals if isinstance(signal, dict)]
    by_level = Counter(item["loop_level"] for item in items)
    execution_capable = [item for item in items if item["can_submit_orders"]]
    unattended_ready = [
        item for item in items
        if item["loop_level"] == "L3" and not item["can_submit_orders"]
    ]
    return {
        "provider": "loop_readiness_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "method": {
            "source": "Adapted from loop-engineering checklist: purpose/scope, scheduling, skills, maker/checker, state, human handoff, cost, observability, safety.",
            "levels": {
                "L0": "Draft/documented intent only",
                "L1": "Report only",
                "L2": "Assisted action with verifier and human gate",
                "L3": "Unattended; not allowed for trading execution loops",
            },
        },
        "summary": {
            "total_loops": len(items),
            "by_level": {level: by_level.get(level, 0) for level in ("L0", "L1", "L2", "L3")},
            "execution_capable_count": len(execution_capable),
            "unattended_ready_count": len(unattended_ready),
            "lowest_score": min((item["readiness_score"] for item in items), default=0),
        },
        "items": sorted(items, key=lambda item: (LEVEL_ORDER.get(item["loop_level"], 9), item["readiness_score"], item["id"] or "")),
        "claude_handoff": {
            "next_task": _next_task(items),
            "commands": [
                "python scripts\\loop_readiness_audit.py --print",
                "python scripts\\execution_gate_audit.py --fail-on-issues --print",
                "python -m pytest agent\\tests\\test_loop_readiness_audit.py -q",
            ],
        },
        "warnings": [
            "Read-only loop governance. No orders, no scheduler changes, no risk changes.",
            "L3 unattended status is not permitted for execution-capable trading loops.",
            "Readiness score is an operations checklist, not alpha evidence.",
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


def write_loop_doc(report: dict[str, Any], path: Path = LOOP_DOC_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report.get("summary", {})
    lines = [
        "# Vibe-Trading Loop Operating System",
        "",
        f"Updated: {report.get('generated_at')}",
        "",
        "## Purpose",
        "",
        "Run trading research and bot governance as durable loops that observe, verify, remember, and escalate before any risky action.",
        "",
        "## Readiness Levels",
        "",
        "- L0 - Draft: documented intent only.",
        "- L1 - Report Only: reads state and writes reports/handoffs; no automatic code, risk, or execution changes.",
        "- L2 - Assisted: may propose small changes only after verifier checks and human approval.",
        "- L3 - Unattended: not allowed for execution-capable trading loops.",
        "",
        "## Current Summary",
        "",
        f"- Total loops: {summary.get('total_loops')}",
        f"- By level: {summary.get('by_level')}",
        f"- Execution-capable loops: {summary.get('execution_capable_count')}",
        f"- Unattended-ready loops: {summary.get('unattended_ready_count')}",
        "",
        "## Operating Rules",
        "",
        "- Every loop starts by reading durable state: registry, reports, logs, and memory.",
        "- Every loop writes an append-only run log or JSON report.",
        "- Use a maker/checker split: the builder cannot approve its own signal or code.",
        "- Any execution, risk, live flag, max contracts, or kill-switch change needs explicit Kenny approval.",
        "- Screenshots, social claims, and agent opinions are idea intake only until independently verified.",
        "- Claude and Codex handoffs must include commands, expected outputs, blockers, and no-trade warnings.",
        "",
        "## Budget And Kill Criteria",
        "",
        "- Default cadence is daily report-only unless a loop has an explicit schedule.",
        "- Stop after one active task unless Kenny explicitly asks for more.",
        "- Pause a loop if tests fail, audit issues appear, state is missing, or the same blocker repeats.",
        "- Do not expand loops just because something is interesting; require an evidence gap.",
        "",
        "## Top Review Items",
        "",
    ]
    for item in report.get("items", [])[:12]:
        lines.append(f"- {item.get('id')}: {item.get('loop_level')} score={item.get('readiness_score')} next={item.get('next_step')}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_handoff(report: dict[str, Any], path: Path = HANDOFF_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    task = report["claude_handoff"]["next_task"]
    commands = report["claude_handoff"].get("commands") or [
        "python scripts\\loop_readiness_audit.py --print",
        "python scripts\\execution_gate_audit.py --fail-on-issues --print",
        "python -m pytest agent\\tests\\test_loop_readiness_audit.py -q",
    ]
    lines = [
        "# Claude Code Handoff - Loop Readiness Audit",
        "",
        f"Date: {report['date']}",
        f"Generated: {report['generated_at']}",
        "",
        "## Objective",
        "",
        "Evaluate the new loop-readiness governance layer and improve documentation/reporting only. Do not enable schedules, execution, or risk changes.",
        "",
        "## Next Task",
        "",
        f"- ID: {task['id']}",
        f"- Title: {task['title']}",
        f"- Instructions: {task['instructions']}",
        "",
        "## Commands",
        "",
        "```powershell",
    ]
    lines.extend(commands)
    lines.extend([
        "```",
        "",
        "## Safety Rules",
        "",
        "- Keep this read-only.",
        "- L3 unattended status is not allowed for trading execution loops.",
        "- The builder cannot approve its own signal.",
        "- Any order, live flag, risk, or kill-switch change requires Kenny approval.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("\nLoop Readiness Audit | read-only")
    print("=" * 76)
    print(
        f"date={report['date']} loops={summary['total_loops']} levels={summary['by_level']} "
        f"execution_capable={summary['execution_capable_count']} unattended_ready={summary['unattended_ready_count']}"
    )
    for item in report["items"][:12]:
        print(f"{item['loop_level']} {item['readiness_score']:>3} {item['id']}: {item['next_step']}")
    print(f"JSON: {REPORT_PATH}")
    print(f"LOOP: {LOOP_DOC_PATH}")
    print(f"Handoff: {HANDOFF_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit loop-engineering readiness for Vibe-Trading components.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--loop-doc-path", type=Path, default=LOOP_DOC_PATH)
    parser.add_argument("--handoff-path", type=Path, default=HANDOFF_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    report = build_report(registry=_read_json(args.registry), day=args.date)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    write_loop_doc(report, args.loop_doc_path)
    write_handoff(report, args.handoff_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Loop readiness audit wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
