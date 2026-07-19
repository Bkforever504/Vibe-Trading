#!/usr/bin/env python3
"""Read-only intake audit for selected external trading skills.

This does not install external skills, import external code, call brokers, or
change bot settings. It turns candidate ideas into a scored local adoption
queue so only bot-improving work gets promoted.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "trading_skills_intake_audit_log.jsonl"

SOURCE_REPO = "https://github.com/agiprolabs/claude-trading-skills"
SELECTED_SKILLS: list[dict[str, Any]] = [
    {
        "skill_id": "walk-forward-validation",
        "source_url": f"{SOURCE_REPO}/tree/main/skills/walk-forward-validation",
        "upstream_status": "documented",
        "bot_gap": "Promotion reviews need a formal out-of-sample and anti-overfit checklist.",
        "improves": ["validation", "promotion_discipline", "anti_overfit"],
        "current_coverage": "partial: strategy_leak_audit catches obvious leaks, but does not score walk-forward quality.",
        "recommended_action": "convert_to_read_only_tool",
        "confidence_score": 92,
        "risk_score": 8,
        "next_local_tool": "walk_forward_promotion_audit",
        "notes": "Highest-value intake. Build as a read-only validator for strategy research and shadow promotion packets.",
    },
    {
        "skill_id": "position-sizing",
        "source_url": f"{SOURCE_REPO}/tree/main/skills/position-sizing",
        "upstream_status": "documented",
        "bot_gap": "Challenge-account and flip-bot sizing need conservative fixed-fractional and binding-constraint review.",
        "improves": ["risk_control", "sizing", "challenge_account_survival"],
        "current_coverage": "partial: execution bots have risk caps and challenge_account_simulator replays closed returns.",
        "recommended_action": "convert_to_read_only_tool",
        "confidence_score": 88,
        "risk_score": 10,
        "next_local_tool": "position_sizing_sanity_report",
        "notes": "Convert ideas into a report that compares configured risk, affordability, drawdown state, and max contract count.",
    },
    {
        "skill_id": "options-pricing",
        "source_url": f"{SOURCE_REPO}/tree/main/skills/options-pricing",
        "upstream_status": "stub",
        "bot_gap": "Options affordability and IV sanity would help, but upstream skill is explicitly incomplete.",
        "improves": ["options_sanity", "iv_review", "greeks_context"],
        "current_coverage": "partial: options_liquidity_feasibility checks price, spread, OI, 0DTE, and weekly availability.",
        "recommended_action": "study_only",
        "confidence_score": 58,
        "risk_score": 18,
        "next_local_tool": "extend_options_liquidity_gate",
        "notes": "Do not import as a dependency. Mine formulas only after local tests; extend existing liquidity/IV tools first.",
    },
    {
        "skill_id": "trade-journal",
        "source_url": f"{SOURCE_REPO}/tree/main/skills/trade-journal",
        "upstream_status": "documented",
        "bot_gap": "Daily review can improve by adding behavior-pattern tags and strategy attribution summaries.",
        "improves": ["daily_learning", "postmortems", "strategy_attribution"],
        "current_coverage": "strong: daily_eod_summary, daily_outcome_reviewer, closed_trade_postmortem, and activity CSV already exist.",
        "recommended_action": "extend_existing_tool",
        "confidence_score": 74,
        "risk_score": 6,
        "next_local_tool": "extend_closed_trade_postmortem",
        "notes": "Use schema ideas to enrich existing logs. Avoid creating a parallel journal that fragments evidence.",
    },
]


def _action_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        action = str(item["recommended_action"])
        counts[action] = counts.get(action, 0) + 1
    return counts


def build_report(day: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    items = sorted(
        SELECTED_SKILLS,
        key=lambda item: (int(item["confidence_score"]) - int(item["risk_score"]), int(item["confidence_score"])),
        reverse=True,
    )
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "trading_skills_intake_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source_repo": SOURCE_REPO,
        "summary": {
            "selected_count": len(items),
            "excluded": ["risk-management"],
            "actions": _action_counts(items),
            "top_candidate": items[0]["skill_id"] if items else None,
        },
        "items": items,
        "warnings": [
            "Read-only idea intake. No external skill is installed or executed.",
            "Recommended actions are not execution approval.",
            "Any converted tool must be local, tested, registered, and pass execution_gate_audit.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> Path:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")
    return log_path


def print_report(report: dict[str, Any]) -> None:
    print("\nTrading Skills Intake Audit | read-only")
    print("=" * 88)
    print(
        f"selected={report['summary']['selected_count']} "
        f"actions={report['summary']['actions']} excluded={report['summary']['excluded']}"
    )
    for item in report["items"]:
        print(
            f"{item['skill_id']:<24} action={item['recommended_action']:<25} "
            f"confidence={item['confidence_score']:>3} risk={item['risk_score']:>2} "
            f"status={item['upstream_status']}"
        )
        print(f"  improves: {', '.join(item['improves'])}")
        print(f"  next: {item['next_local_tool']}")
    print("\nNo orders placed. No settings changed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    report = build_report(args.date)
    if args.print_output:
        print_report(report)
    if not args.no_write:
        append_log(report, args.log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
