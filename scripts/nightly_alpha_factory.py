#!/usr/bin/env python3
"""Build the read-only Nightly Alpha Factory morning report.

This is a coordinator, not an executor. It assembles existing scanner, learning,
audit, and regime reports into the six-agent research pipeline Kenny asked for:
idea intake, feature build, replay/backtest evidence, overfit kill, regime
validation, and governance handoff.
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
REPORT_PATH = REPORT_DIR / "nightly-alpha-factory.json"
LOG_PATH = ROOT / "data" / "nightly_alpha_factory_log.jsonl"
HANDOFF_PATH = ROOT / "CODEx_CLAUDE_COLLAB" / "CLAUDE_HANDOFF_NIGHTLY_ALPHA_FACTORY_2026-07-06.md"

FORBIDDEN_ACTIONS = [
    "Do not enable live trading.",
    "Do not change risk thresholds, max contracts, kill switches, or manual-reset files.",
    "Do not promote a scanner into an execution gate without rules/signal_promotion_rules.md.",
    "Do not wire creator/social/crowded-positioning context directly to orders.",
    "Do not let the agent that generated an idea approve that same idea.",
]

AGENTS = [
    {
        "id": "idea_intake_agent",
        "role": "Find raw ideas from creator watchlists, cheap asymmetry, missed bangers, research intake, and social context.",
        "approval_power": "none",
    },
    {
        "id": "feature_builder_agent",
        "role": "Map ideas to measurable features, symbols, option costs, liquidity, and repeatable evidence fields.",
        "approval_power": "none",
    },
    {
        "id": "backtest_replay_agent",
        "role": "Attach replay/shadow outcomes, P/L, capture efficiency, and sample counts.",
        "approval_power": "none",
    },
    {
        "id": "overfit_killer_agent",
        "role": "Reject ideas that only worked once, lack samples, leak future data, or are just hindsight screenshots.",
        "approval_power": "veto_only",
    },
    {
        "id": "regime_validator_agent",
        "role": "Check whether the idea still makes sense under current market force, crowding, breadth, and volatility context.",
        "approval_power": "veto_only",
    },
    {
        "id": "governance_chair_agent",
        "role": "Produce the morning handoff and keep every promotion behind dual review and Kenny approval.",
        "approval_power": "handoff_only",
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _top_cheap_opportunities(cheap: dict[str, Any]) -> list[dict[str, Any]]:
    rows = cheap.get("top_candidates") if isinstance(cheap.get("top_candidates"), list) else []
    output: list[dict[str, Any]] = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        output.append({
            "symbol": row.get("symbol"),
            "source": "cheap_asymmetry_scanner",
            "reason": "cheap_asymmetry",
            "best_return_pct": row.get("best_return_pct"),
            "cost_at_open": row.get("cost_at_open"),
            "goal_match": bool(row.get("goal_match")),
            "approval_state": "observe_only",
        })
    return output


def _creator_opportunities(creator: dict[str, Any], existing: set[str]) -> list[dict[str, Any]]:
    rows = creator.get("watchlist_results") if isinstance(creator.get("watchlist_results"), list) else []
    output: list[dict[str, Any]] = []
    for row in rows[:15]:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        if not symbol or symbol in existing:
            continue
        verdict = str(row.get("verdict") or "")
        if verdict not in {"strong_runner_confirmed", "runner_confirmed"}:
            continue
        output.append({
            "symbol": symbol,
            "source": "creator_watchlist_runner_scanner",
            "reason": verdict,
            "best_return_pct": row.get("best_return_pct"),
            "cost_at_open": row.get("cost_at_open"),
            "goal_match": False,
            "approval_state": "observe_only",
        })
    return output


def _build_opportunity_queue(cheap: dict[str, Any], creator: dict[str, Any]) -> list[dict[str, Any]]:
    queue = _top_cheap_opportunities(cheap)
    existing = {str(row.get("symbol") or "") for row in queue}
    queue.extend(_creator_opportunities(creator, existing))
    queue.sort(
        key=lambda row: (
            bool(row.get("goal_match")),
            _safe_float(row.get("best_return_pct")),
        ),
        reverse=True,
    )
    return queue[:12]


def _idea_intake(cheap: dict[str, Any], creator: dict[str, Any], nightly: dict[str, Any]) -> dict[str, Any]:
    creator_summary = creator.get("summary") if isinstance(creator.get("summary"), dict) else {}
    cheap_summary = cheap.get("summary") if isinstance(cheap.get("summary"), dict) else {}
    active_tasks = nightly.get("active_tasks") if isinstance(nightly.get("active_tasks"), list) else []
    return {
        "cheap_asymmetry_candidates": _safe_int(cheap.get("candidate_count")),
        "cheap_goal_matches": _safe_int(cheap_summary.get("goal_match_count")),
        "creator_symbols": _safe_int(creator_summary.get("symbol_count")),
        "creator_runners": _safe_int(creator_summary.get("runner_count")),
        "creator_cheap_asymmetry": _safe_int(creator_summary.get("cheap_asymmetry_count")),
        "nightly_research_active_tasks": len(active_tasks),
    }


def _validation_state(execution_audit: dict[str, Any], strategy_leak: dict[str, Any], skills_audit: dict[str, Any]) -> dict[str, Any]:
    leak_summary = strategy_leak.get("summary") if isinstance(strategy_leak.get("summary"), dict) else {}
    skills_summary = skills_audit.get("summary") if isinstance(skills_audit.get("summary"), dict) else {}
    return {
        "execution_gate": {
            "passed": execution_audit.get("passed"),
            "issue_count": _safe_int(execution_audit.get("issue_count")),
            "warning_count": _safe_int(execution_audit.get("warning_count")),
        },
        "strategy_leak": {
            "passed": strategy_leak.get("passed"),
            "critical_count": _safe_int(leak_summary.get("critical")),
            "issue_count": _safe_int(strategy_leak.get("issue_count")),
        },
        "trading_skills_intake": {
            "passed": skills_audit.get("passed"),
            "issue_count": _safe_int(skills_audit.get("issue_count")),
            "review_count": _safe_int(skills_summary.get("review_count")),
        },
    }


def _regime_state(crowded: dict[str, Any], market_force: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    crowded_summary = crowded.get("summary") if isinstance(crowded.get("summary"), dict) else {}
    flip_context = crowded.get("flip_bot_context") if isinstance(crowded.get("flip_bot_context"), dict) else {}
    health_summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    return {
        "crowded_side": crowded_summary.get("crowded_side"),
        "crowding_score": crowded_summary.get("crowding_score"),
        "flip_posture": flip_context.get("posture"),
        "market_force_score": market_force.get("market_force_score") or market_force.get("score"),
        "signal_health": health_summary,
    }


def _learning_state(flip_learning: dict[str, Any]) -> dict[str, Any]:
    actual = flip_learning.get("actual") if isinstance(flip_learning.get("actual"), dict) else {}
    lessons = flip_learning.get("lessons") if isinstance(flip_learning.get("lessons"), list) else []
    severe = [row for row in lessons if isinstance(row, dict) and row.get("severity") in {"high", "critical"}]
    return {
        "flip_closed_count": _safe_int(actual.get("closed_count")),
        "flip_net_pnl": round(_safe_float(actual.get("net_pnl")), 2),
        "lesson_count": len(lessons),
        "high_severity_lessons": len(severe),
        "top_lessons": lessons[:5],
    }


def _loop_readiness_state(loop_readiness: dict[str, Any]) -> dict[str, Any]:
    summary = loop_readiness.get("summary") if isinstance(loop_readiness.get("summary"), dict) else {}
    next_task = {}
    handoff = loop_readiness.get("claude_handoff") if isinstance(loop_readiness.get("claude_handoff"), dict) else {}
    if isinstance(handoff.get("next_task"), dict):
        next_task = handoff["next_task"]
    return {
        "total_loops": _safe_int(summary.get("total_loops")),
        "by_level": summary.get("by_level") if isinstance(summary.get("by_level"), dict) else {},
        "execution_capable_count": _safe_int(summary.get("execution_capable_count")),
        "unattended_ready_count": _safe_int(summary.get("unattended_ready_count")),
        "next_task_id": next_task.get("id"),
    }


def _repo_candidate_state(report: dict[str, Any]) -> tuple[Any, int, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    queue = report.get("local_upgrade_queue") if isinstance(report.get("local_upgrade_queue"), list) else []
    next_tool = queue[0].get("next_local_tool") if queue and isinstance(queue[0], dict) else None
    return summary.get("top_candidate"), len(queue), next_tool


def _external_repo_intake_state(mahoraga: dict[str, Any], openalice: dict[str, Any]) -> dict[str, Any]:
    mahoraga_top, mahoraga_count, mahoraga_tool = _repo_candidate_state(mahoraga)
    openalice_top, openalice_count, openalice_tool = _repo_candidate_state(openalice)
    return {
        "mahoraga_top_candidate": mahoraga_top,
        "mahoraga_queue_count": mahoraga_count,
        "mahoraga_next_tool": mahoraga_tool,
        "openalice_top_candidate": openalice_top,
        "openalice_queue_count": openalice_count,
        "openalice_next_tool": openalice_tool,
        "execution_enabled": False,
    }


def _incentive_safety_state(incentive_safety: dict[str, Any]) -> dict[str, Any]:
    summary = incentive_safety.get("summary") if isinstance(incentive_safety.get("summary"), dict) else {}
    blockers = incentive_safety.get("promotion_blockers") if isinstance(incentive_safety.get("promotion_blockers"), list) else []
    return {
        "passed": incentive_safety.get("passed"),
        "total_components": _safe_int(summary.get("total_components")),
        "issue_count": _safe_int(summary.get("issue_count")),
        "high_risk_count": _safe_int(summary.get("high_risk_count")),
        "medium_risk_count": _safe_int(summary.get("medium_risk_count")),
        "promotion_blockers": blockers[:10],
    }


def _governance(
    *,
    cheap: dict[str, Any],
    execution_audit: dict[str, Any],
    validation: dict[str, Any],
    learning: dict[str, Any],
    incentive_safety: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    if execution_audit.get("passed") is False or _safe_int(execution_audit.get("issue_count")):
        blockers.append("execution_audit_failed")
    if validation["strategy_leak"].get("critical_count"):
        blockers.append("strategy_leak_critical")
    if learning.get("high_severity_lessons"):
        blockers.append("unresolved_flip_learning_lessons")
    cheap_summary = cheap.get("summary") if isinstance(cheap.get("summary"), dict) else {}
    if not _safe_int(cheap_summary.get("goal_match_count")):
        blockers.append("no_repeated_goal_match_evidence")
    if _safe_int(incentive_safety.get("high_risk_count")):
        blockers.append("incentive_safety_findings")
    return {
        "builder_cannot_approve_itself": True,
        "promotion_requires": [
            "30 trading days of read-only evidence",
            "10 completed samples per symbol or setup",
            "liquidity feasibility proof",
            "strategy leak audit pass",
            "execution gate audit pass",
            "dual Codex/Claude review",
            "explicit Kenny approval",
        ],
        "blockers": blockers,
        "forbidden_actions": FORBIDDEN_ACTIONS,
    }


def _promotion_summary(cheap: dict[str, Any], governance: dict[str, Any]) -> dict[str, Any]:
    cheap_summary = cheap.get("summary") if isinstance(cheap.get("summary"), dict) else {}
    raw_goal_matches = _safe_int(cheap_summary.get("goal_match_count"))
    return {
        "raw_goal_matches": raw_goal_matches,
        "promotion_ready_count": 0,
        "why_zero": "Goal matches are observation-only until sample count, liquidity, audits, dual review, and approval are complete.",
        "active_blockers": governance["blockers"],
    }


def _next_task(governance: dict[str, Any], queue: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = set(governance.get("blockers") or [])
    if "execution_audit_failed" in blockers:
        return {
            "id": "fix-execution-audit-first",
            "title": "Fix execution audit before research expansion",
            "instructions": "Run scripts\\execution_gate_audit.py, remove any accidental order/live wiring from non-execution components, then rerun targeted tests.",
        }
    if queue:
        top = queue[0]
        return {
            "id": "monitor-cheap-asymmetry",
            "title": f"Collect another evidence day for {top.get('symbol')}",
            "instructions": "Do not promote. Compare creator/watchlist context, cheap option return, capture efficiency, liquidity, and Flip Bot selection gap after the next close.",
        }
    return {
        "id": "observe-no-build",
        "title": "No new build: collect another clean evidence day",
        "instructions": "Keep scanners running and avoid adding noisy lanes without an EOD evidence gap.",
    }


def build_report(day: str | None = None, report_dir: Path = REPORT_DIR) -> dict[str, Any]:
    day = day or date.today().isoformat()
    cheap = _read_json(report_dir / "cheap-asymmetry-scanner.json")
    creator = _read_json(report_dir / "creator-watchlist-runner-scanner.json")
    flip_learning = _read_json(report_dir / "flip-bot-learning-report.json")
    crowded = _read_json(report_dir / "crowded-positioning-scanner.json")
    market_force = _read_json(report_dir / "market-force-score.json")
    health = _read_json(report_dir / "signal-stack-health.json")
    execution_audit = _read_json(report_dir / "execution-gate-audit.json")
    strategy_leak = _read_json(report_dir / "strategy-leak-audit.json")
    skills_audit = _read_json(report_dir / "trading-skills-intake-audit.json")
    nightly = _read_json(report_dir / "nightly-research-queue.json")
    loop_readiness_report = _read_json(report_dir / "loop-readiness-audit.json")
    mahoraga_intake = _read_json(report_dir / "mahoraga-repo-intake-audit.json")
    openalice_intake = _read_json(report_dir / "openalice-repo-intake-audit.json")
    incentive_safety_report = _read_json(report_dir / "agent-incentive-safety-audit.json")

    queue = _build_opportunity_queue(cheap, creator)
    idea_intake = _idea_intake(cheap, creator, nightly)
    validation = _validation_state(execution_audit, strategy_leak, skills_audit)
    regime = _regime_state(crowded, market_force, health)
    learning = _learning_state(flip_learning)
    loop_readiness = _loop_readiness_state(loop_readiness_report)
    external_repo_intake = _external_repo_intake_state(mahoraga_intake, openalice_intake)
    incentive_safety = _incentive_safety_state(incentive_safety_report)
    governance = _governance(
        cheap=cheap,
        execution_audit=execution_audit,
        validation=validation,
        learning=learning,
        incentive_safety=incentive_safety,
    )
    promotion = _promotion_summary(cheap, governance)
    next_task = _next_task(governance, queue)
    candidate_count = len(queue)
    headline = f"{candidate_count} idea(s) queued, {promotion['promotion_ready_count']} promoted, {len(governance['blockers'])} blocker(s)."

    return {
        "provider": "nightly_alpha_factory",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "headline": headline,
        "agents": AGENTS,
        "idea_intake": idea_intake,
        "feature_builder": {
            "tracked_features": [
                "symbol",
                "option_cost",
                "best_return_pct",
                "capture_efficiency",
                "creator_context",
                "liquidity_status",
                "crowding_context",
            ],
            "output": "opportunity_queue",
        },
        "backtest_replay": {
            "source": "shadow_and_closed_trade_reports",
            "note": "Phase 1 uses existing shadow replay/P&L reports; no claim of 20-year validation yet.",
        },
        "overfit_killer": validation,
        "regime_validator": regime,
        "learning": learning,
        "loop_readiness": loop_readiness,
        "external_repo_intake": external_repo_intake,
        "incentive_safety": incentive_safety,
        "opportunity_queue": queue,
        "governance": governance,
        "promotion_summary": promotion,
        "claude_handoff": {
            "next_task": next_task,
            "commands": [
                "python scripts\\nightly_alpha_factory.py --print",
                "python scripts\\execution_gate_audit.py --fail-on-issues --print",
                "python -m pytest agent\\tests\\test_nightly_alpha_factory.py -q",
            ],
        },
        "warnings": [
            "This is a morning research coordinator, not an autonomous trader.",
            "No broker calls. No orders placed. No settings changed.",
            "Screenshots and social claims are discovery prompts only.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def write_handoff(report: dict[str, Any], path: Path = HANDOFF_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    next_task = report["claude_handoff"]["next_task"]
    commands = report["claude_handoff"].get("commands") or [
        "python scripts\\nightly_alpha_factory.py --print",
        "python scripts\\execution_gate_audit.py --fail-on-issues --print",
        "python -m pytest agent\\tests\\test_nightly_alpha_factory.py -q",
    ]
    queue = report.get("opportunity_queue") if isinstance(report.get("opportunity_queue"), list) else []
    lines = [
        "# Claude Code Handoff - Nightly Alpha Factory",
        "",
        f"Date: {report['date']}",
        f"Generated: {report['generated_at']}",
        "",
        "## Objective",
        "",
        "Implement and evaluate the read-only alpha-factory loop without enabling execution. The builder cannot approve its own signal.",
        "",
        "## Current Report",
        "",
        f"- Headline: {report.get('headline')}",
        f"- Execution enabled: {report.get('execution_enabled')}",
        f"- Can submit orders: {report.get('can_submit_orders')}",
        f"- Loop readiness: {report.get('loop_readiness')}",
        f"- External repo intake: {report.get('external_repo_intake')}",
        "",
        "## Next Task",
        "",
        f"- ID: {next_task['id']}",
        f"- Title: {next_task['title']}",
        f"- Instructions: {next_task['instructions']}",
        "",
        "## Opportunity Queue",
        "",
    ]
    if queue:
        lines.extend(
            f"- {row.get('symbol')}: {row.get('reason')} ret={row.get('best_return_pct')} approval={row.get('approval_state')}"
            for row in queue[:10]
        )
    else:
        lines.append("- Empty.")
    lines.extend([
        "",
        "## Governance Rules",
        "",
        "- The builder cannot approve its own signal.",
    ])
    lines.extend(f"- {item}" for item in report["governance"]["forbidden_actions"])
    lines.extend([
        "",
        "## Commands",
        "",
        "```powershell",
    ])
    lines.extend(commands)
    lines.extend([
        "```",
        "",
        "## Verification Required",
        "",
        "- Targeted tests pass.",
        "- Execution gate audit passes with zero issues.",
        "- Report remains read-only with execution_enabled=false and can_submit_orders=false.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nNightly Alpha Factory | read-only")
    print("=" * 76)
    print(report["headline"])
    print(f"date={report['date']} execution_enabled={report['execution_enabled']} can_submit_orders={report['can_submit_orders']}")
    print(f"next={report['claude_handoff']['next_task']['id']}: {report['claude_handoff']['next_task']['title']}")
    for row in report["opportunity_queue"][:8]:
        print(f"- {row.get('symbol')}: {row.get('reason')} ret={row.get('best_return_pct')} approval={row.get('approval_state')}")
    print(f"JSON: {REPORT_PATH}")
    print(f"Handoff: {HANDOFF_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the read-only Nightly Alpha Factory report.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--handoff-path", type=Path, default=HANDOFF_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    report = build_report(day=args.date, report_dir=args.report_dir)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    write_handoff(report, args.handoff_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Nightly alpha factory wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
