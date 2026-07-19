#!/usr/bin/env python3
"""Read-only incentive safety audit for autonomous trading loops.

This translates the Agents of Chaos warning into local governance checks:
clear objectives, explicit non-goals, stop conditions, external verification,
and no self-approval for anything that can affect execution.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "research" / "signal_registry.json"
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "agent-incentive-safety-audit.json"
LOG_PATH = ROOT / "data" / "agent_incentive_safety_audit_log.jsonl"
HANDOFF_PATH = ROOT / "CODEx_CLAUDE_COLLAB" / "CLAUDE_HANDOFF_AGENT_INCENTIVE_SAFETY_2026-07-06.md"

DANGEROUS_OBJECTIVE_PATTERNS = [
    re.compile(r"maximize\s+profit", re.IGNORECASE),
    re.compile(r"at\s+all\s+costs", re.IGNORECASE),
    re.compile(r"ignore\s+(?:risk|guard|gate|approval)", re.IGNORECASE),
    re.compile(r"bypass\s+(?:risk|guard|gate|approval)", re.IGNORECASE),
]

SELF_APPROVAL_PATTERNS = [
    re.compile(r"self[-_\s]?approve", re.IGNORECASE),
    re.compile(r"approves?\s+itself", re.IGNORECASE),
    re.compile(r"builder\s+approves?", re.IGNORECASE),
]

UNBOUNDED_AUTONOMY_PATTERNS = [
    re.compile(r"\b24/7\b", re.IGNORECASE),
    re.compile(r"unattended", re.IGNORECASE),
    re.compile(r"autonomous", re.IGNORECASE),
]

HUMAN_GATE_TERMS = ("kenny approval", "explicit approval", "human approval", "manual approval", "dual review")
FORBIDDEN_TERMS = ("forbidden", "non-goal", "non-goals", "must not", "no broker", "no account")
STOP_TERMS = ("stop", "kill switch", "stale", "staleness", "circuit breaker", "halt", "market_closed")
VERIFIER_TERMS = ("verifier", "separate audit", "execution_gate_audit", "strategy_leak_audit", "dual codex/claude")
EVIDENCE_TERMS = ("30 trading days", "10 samples", "evidence", "shadow", "sample")

REQUIRED_POLICY_FIELDS = [
    "objective",
    "non_goals",
    "forbidden_actions",
    "escalation_triggers",
    "evidence_standard",
    "max_autonomy_level",
    "verifier_owner",
]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = _read_json(path)
    if not isinstance(registry.get("signals"), list):
        raise ValueError("signal_registry.json must contain a signals list")
    return registry


def _joined_metadata(signal: dict[str, Any]) -> str:
    fields = [
        signal.get("id"),
        signal.get("name"),
        signal.get("status"),
        signal.get("broker_or_venue"),
        signal.get("evidence_gate"),
        signal.get("notes"),
    ]
    feeds = signal.get("feeds")
    if isinstance(feeds, list):
        fields.extend(str(feed) for feed in feeds)
    return " ".join(str(field or "") for field in fields).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_stop_condition(text: str) -> bool:
    if re.search(r"\bno\s+(?:stop|halt|kill switch|circuit breaker)", text, re.IGNORECASE):
        return False
    return _has_any(text, STOP_TERMS)


def _matches(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    return [pattern.pattern for pattern in patterns if pattern.search(text)]


def _risk_level(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _issue(name: str, severity: str, detail: str) -> dict[str, str]:
    return {"issue": name, "severity": severity, "detail": detail}


def evaluate_signal(signal: dict[str, Any]) -> dict[str, Any]:
    text = _joined_metadata(signal)
    issues: list[dict[str, str]] = []
    strengths: list[str] = []
    risk_score = 0
    execution_capable = bool(signal.get("execution_enabled")) or bool(signal.get("can_submit_orders"))

    if not execution_capable:
        strengths.append("read_only_default")
    if _has_any(text, HUMAN_GATE_TERMS):
        strengths.append("human_gate")
    if _has_any(text, FORBIDDEN_TERMS):
        strengths.append("forbidden_actions")
    has_stop_condition = _has_stop_condition(text)
    if has_stop_condition:
        strengths.append("stop_conditions")
    if _has_any(text, VERIFIER_TERMS):
        strengths.append("separate_verifier")
    if _has_any(text, EVIDENCE_TERMS):
        strengths.append("evidence_standard")

    if execution_capable:
        risk_score += 30
        issues.append(_issue(
            "execution_capable_requires_incentive_review",
            "high",
            "Any component that can affect execution needs explicit incentive controls and human approval metadata.",
        ))

    dangerous_hits = _matches(text, DANGEROUS_OBJECTIVE_PATTERNS)
    if dangerous_hits:
        risk_score += 30
        issues.append(_issue(
            "dangerous_objective_language",
            "high",
            "Objective language optimizes outcome without enough governance context.",
        ))

    if _matches(text, SELF_APPROVAL_PATTERNS):
        risk_score += 25
        issues.append(_issue(
            "self_approval_risk",
            "high",
            "The component appears able to approve or validate its own work.",
        ))

    if not has_stop_condition:
        risk_score += 15
        issues.append(_issue(
            "missing_stop_conditions",
            "medium",
            "No obvious stop, stale-data, halt, or circuit-breaker language in registry metadata.",
        ))

    if execution_capable and not _has_any(text, HUMAN_GATE_TERMS):
        risk_score += 15
        issues.append(_issue(
            "missing_human_gate",
            "medium",
            "Execution-capable component lacks explicit human approval language.",
        ))

    if execution_capable and not _has_any(text, VERIFIER_TERMS):
        risk_score += 10
        issues.append(_issue(
            "missing_separate_verifier",
            "medium",
            "Execution-capable component lacks an obvious independent verifier.",
        ))

    if _matches(text, UNBOUNDED_AUTONOMY_PATTERNS) and not has_stop_condition:
        risk_score += 10
        issues.append(_issue(
            "unbounded_autonomy_language",
            "medium",
            "Autonomy wording appears without matching stop conditions.",
        ))

    risk_score = max(0, min(100, risk_score - len(strengths) * 5))
    return {
        "id": signal.get("id"),
        "name": signal.get("name"),
        "script": signal.get("script"),
        "status": signal.get("status"),
        "execution_capable": execution_capable,
        "risk_score": risk_score,
        "risk_level": _risk_level(risk_score),
        "issues": issues,
        "strengths": strengths,
    }


def build_report(registry: dict[str, Any], day: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    signals = registry.get("signals") if isinstance(registry.get("signals"), list) else []
    items = [evaluate_signal(signal) for signal in signals if isinstance(signal, dict)]
    issue_count = sum(len(item["issues"]) for item in items)
    high_risk = [item for item in items if item["risk_level"] == "high"]
    medium_risk = [item for item in items if item["risk_level"] == "medium"]
    execution_capable = [item for item in items if item["execution_capable"]]
    blockers = [str(item["id"]) for item in high_risk]

    return {
        "provider": "agent_incentive_safety_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "passed": not high_risk,
        "summary": {
            "total_components": len(items),
            "issue_count": issue_count,
            "high_risk_count": len(high_risk),
            "medium_risk_count": len(medium_risk),
            "execution_capable_count": len(execution_capable),
        },
        "required_policy_fields": REQUIRED_POLICY_FIELDS,
        "promotion_blockers": blockers,
        "items": sorted(items, key=lambda item: (item["risk_score"], len(item["issues"])), reverse=True),
        "claude_handoff": {
            "next_task": {
                "id": "review-agent-incentives",
                "title": "Add missing incentive controls to high-risk loops before promotion",
                "instructions": "Patch registry metadata first. Do not change broker wiring, risk thresholds, or execution flags.",
            },
            "commands": [
                "python scripts\\agent_incentive_safety_audit.py --print",
                "python scripts\\nightly_alpha_factory.py --print",
                "python scripts\\execution_gate_audit.py --fail-on-issues --print",
                "python -m pytest agent\\tests\\test_agent_incentive_safety_audit.py agent\\tests\\test_nightly_alpha_factory.py -q",
            ],
        },
        "warnings": [
            "Read-only governance audit inspired by Agents of Chaos.",
            "Do not let a signal builder approve its own promotion.",
            "Do not use profit-only objectives without non-goals, stop conditions, evidence standards, and human approval.",
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
    next_task = report["claude_handoff"]["next_task"]
    lines = [
        "# Claude Code Handoff - Agent Incentive Safety",
        "",
        f"Date: {report['date']}",
        f"Generated: {report['generated_at']}",
        "",
        "## Objective",
        "",
        "Turn the Agents of Chaos lesson into practical Vibe-Trading governance: every autonomous or execution-capable loop needs explicit objectives, non-goals, forbidden actions, stop conditions, evidence standards, and independent review.",
        "",
        "## Current State",
        "",
        f"- Passed: {report['passed']}",
        f"- Components: {report['summary']['total_components']}",
        f"- Issues: {report['summary']['issue_count']}",
        f"- High risk: {report['summary']['high_risk_count']}",
        f"- Medium risk: {report['summary']['medium_risk_count']}",
        f"- Execution capable: {report['summary']['execution_capable_count']}",
        "",
        "## Next Task",
        "",
        f"- ID: {next_task['id']}",
        f"- Title: {next_task['title']}",
        f"- Instructions: {next_task['instructions']}",
        "",
        "## Required Policy Fields",
        "",
    ]
    lines.extend(f"- {field}" for field in report["required_policy_fields"])
    lines.extend([
        "",
        "## Promotion Blockers",
        "",
    ])
    blockers = report.get("promotion_blockers") or []
    if blockers:
        lines.extend(f"- {item}" for item in blockers)
    else:
        lines.append("- None at high-risk level.")
    lines.extend([
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
    summary = report["summary"]
    print("\nAgent Incentive Safety Audit | read-only")
    print("=" * 88)
    print(
        f"passed={report['passed']} components={summary['total_components']} "
        f"issues={summary['issue_count']} high={summary['high_risk_count']} "
        f"medium={summary['medium_risk_count']} execution_capable={summary['execution_capable_count']}"
    )
    for item in report["items"][:12]:
        if item["issues"]:
            names = ",".join(issue["issue"] for issue in item["issues"][:3])
            print(f"{item['id']:<36} risk={item['risk_level']:<6} score={item['risk_score']:<3} issues={names}")
    print(f"JSON: {REPORT_PATH}")
    print(f"Handoff: {HANDOFF_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only incentive safety audit for trading loops.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--handoff-path", type=Path, default=HANDOFF_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    report = build_report(load_registry(args.registry), day=args.date)
    if not args.no_write:
        write_report(report, args.report_path)
        append_log(report, args.log_path)
        write_handoff(report, args.handoff_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Agent incentive safety audit wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
