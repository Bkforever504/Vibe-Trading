from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUEUE_FILE = ROOT / "research" / "strategy_intake" / "strategy_queue.json"
REPORT_FILE = Path.home() / ".vibe-trading" / "reports" / "strategy-intake-report.json"

RULE_FIELDS = (
    "entry_rules",
    "stop_loss_rules",
    "take_profit_rules",
    "exit_rules",
    "position_sizing",
    "session_rules",
)
STATUS_FIELDS = ("pine_status", "python_status", "backtest_status", "decision")
UNCLEAR_TOKENS = ("tbd", "unknown", "not specified", "unclear", "needs review")


@dataclass(frozen=True)
class IntakeEvaluation:
    item: dict[str, Any]
    readiness_score: float
    stage: str
    blockers: list[str]
    strengths: list[str]
    next_action: str


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_clear(value: Any) -> bool:
    text = _text(value).lower()
    if not text:
        return False
    return not any(token in text for token in UNCLEAR_TOKENS)


def _has_any(value: Any) -> bool:
    return bool(_text(value))


def load_queue(path: Path = QUEUE_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def evaluate_item(item: dict[str, Any]) -> IntakeEvaluation:
    blockers: list[str] = []
    strengths: list[str] = []
    score = 0.0

    clear_rule_count = sum(1 for field in RULE_FIELDS if _is_clear(item.get(field)))
    score += (clear_rule_count / len(RULE_FIELDS)) * 3.0
    if clear_rule_count == len(RULE_FIELDS):
        strengths.append("complete rule set")
    else:
        blockers.append("rule fields incomplete or ambiguous")

    ambiguities = [str(value) for value in _safe_list(item.get("ambiguities")) if str(value).strip()]
    if len(ambiguities) <= 2:
        score += 1.0
        strengths.append("low ambiguity count")
    elif len(ambiguities) <= 4:
        score += 0.5
    else:
        blockers.append("too many unresolved ambiguities")

    rejection_reasons = [str(value) for value in _safe_list(item.get("rejection_reasons")) if str(value).strip()]
    if rejection_reasons:
        score -= min(2.0, len(rejection_reasons) * 0.75)
        blockers.extend(rejection_reasons)
    else:
        score += 1.0
        strengths.append("no pre-existing rejection reason")

    source_platform = _text(item.get("source_platform")).lower()
    if any(token in source_platform for token in ("github", "academic", "quantified", "web")):
        score += 1.0
        strengths.append("source is structurally testable")
    elif source_platform:
        score += 0.4

    license_notes = _text(item.get("license_or_permission_notes")).lower()
    if "check repo license" in license_notes or not license_notes:
        blockers.append("license or permission needs review")
    else:
        score += 1.0
        strengths.append("license/permission note present")

    pine_status = _text(item.get("pine_status")) or "not_started"
    python_status = _text(item.get("python_status")) or "not_started"
    backtest_status = _text(item.get("backtest_status")) or "pending"
    decision = _text(item.get("decision")) or "pending"

    if pine_status == "needs_scan":
        blockers.append("Pine source scan required")
    elif pine_status in {"done", "not_required"}:
        score += 0.75

    if python_status == "done":
        score += 1.0
    elif python_status == "in_progress":
        score += 0.5

    if backtest_status == "done":
        score += 1.0
    elif backtest_status in {"pending", "not_started"}:
        blockers.append("backtest pending")

    if decision == "rejected":
        stage = "rejected"
        score = min(score, 2.0)
    elif blockers and "Pine source scan required" in blockers:
        stage = "needs_scan"
    elif blockers and "rule fields incomplete or ambiguous" in blockers:
        stage = "needs_rules"
    elif backtest_status in {"pending", "not_started"} and python_status == "not_started":
        stage = "ready_for_port" if clear_rule_count == len(RULE_FIELDS) and len(ambiguities) <= 4 else "triage"
    elif backtest_status == "done" and decision in {"paper_candidate", "shadow_candidate"}:
        stage = "shadow_candidate"
    elif backtest_status == "done":
        stage = "review_backtest"
    else:
        stage = "triage"

    next_action = _text(item.get("next_action"))
    if not next_action:
        next_action = {
            "needs_scan": "Run Pine source scan and license review.",
            "needs_rules": "Resolve ambiguous entry/exit/risk rules before coding.",
            "ready_for_port": "Port to Python and run the backtest gate.",
            "review_backtest": "Review metrics against OOS/WF/PBO/DD gates.",
            "shadow_candidate": "Build or verify shadow logger.",
            "rejected": "Leave parked unless source assumptions materially change.",
        }.get(stage, "Review strategy intake item.")

    return IntakeEvaluation(
        item=item,
        readiness_score=round(max(0.0, min(score, 10.0)), 2),
        stage=stage,
        blockers=blockers,
        strengths=strengths,
        next_action=next_action,
    )


def build_report(queue: list[dict[str, Any]]) -> dict[str, Any]:
    evaluations = [evaluate_item(item) for item in queue]
    counts: dict[str, int] = {}
    for evaluation in evaluations:
        counts[evaluation.stage] = counts.get(evaluation.stage, 0) + 1

    rows = []
    for evaluation in sorted(evaluations, key=lambda e: (e.readiness_score, e.item.get("id", "")), reverse=True):
        item = evaluation.item
        rows.append({
            "id": _text(item.get("id")),
            "source_platform": _text(item.get("source_platform")),
            "source_url": _text(item.get("source_url")),
            "trader": _text(item.get("trader")),
            "strategy_name": _text(item.get("strategy_name")),
            "market": _text(item.get("market")),
            "timeframe": _text(item.get("timeframe")),
            "stage": evaluation.stage,
            "readiness_score": evaluation.readiness_score,
            "pine_status": _text(item.get("pine_status")),
            "python_status": _text(item.get("python_status")),
            "backtest_status": _text(item.get("backtest_status")),
            "decision": _text(item.get("decision")),
            "ambiguity_count": len(_safe_list(item.get("ambiguities"))),
            "blockers": evaluation.blockers,
            "strengths": evaluation.strengths,
            "next_action": evaluation.next_action,
        })

    return {
        "provider": "strategy_intake",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "research_only",
        "execution_enabled": False,
        "queue_count": len(queue),
        "stage_counts": counts,
        "items": rows,
        "top_next_actions": rows[:5],
        "warnings": [
            "Research-only strategy discovery queue. No broker execution is wired.",
            "Every candidate must pass red-flag, OOS, walk-forward, PBO, drawdown, and forward-test gates.",
            "TradingView/Pine results are visual sanity checks, not sufficient proof.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def run_report(*, queue_path: Path = QUEUE_FILE, out: Path = REPORT_FILE) -> dict[str, Any]:
    report = build_report(load_queue(queue_path))
    write_report(report, out)
    return report
