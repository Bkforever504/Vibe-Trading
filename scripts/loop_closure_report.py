#!/usr/bin/env python3
"""Build a read-only loop-closure report for bot decisions and learning.

The goal is one daily chain:
scanner -> decision -> trade/no-trade -> exit quality -> P/L explanation -> lesson -> next-day gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from flip_exit_taxonomy import classify_exit_quality
except ModuleNotFoundError:
    from scripts.flip_exit_taxonomy import classify_exit_quality

try:
    from options_reporting import dedupe_options_trade_records
except ModuleNotFoundError:
    from scripts.options_reporting import dedupe_options_trade_records


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"

FLIP_TRADES_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_TRADES_PATH = VIBE_HOME / "options-trades.json"
OPTIONS_DECISIONS_PATH = VIBE_HOME / "logs" / "options-decisions.jsonl"
POSTMORTEM_PATH = REPORT_DIR / "closed-trade-postmortem.json"
GRADES_PATH = REPORT_DIR / "signal-stack-grades.json"
CHEAP_ASYMMETRY_PATH = REPORT_DIR / "cheap-asymmetry-scanner.json"
LEARNING_PATH = REPORT_DIR / "flip-bot-learning-report.json"

REPORT_PATH = REPORT_DIR / "loop-closure-report.json"
LOG_PATH = ROOT / "data" / "loop_closure_report_log.jsonl"
LESSON_LEDGER_PATH = ROOT / "data" / "trade_lesson_ledger.jsonl"
LESSON_REPORT_PATH = REPORT_DIR / "trade-lesson-ledger.json"
HANDOFF_PATH = ROOT / "CODEx_CLAUDE_COLLAB" / "CLAUDE_HANDOFF_LOOP_CLOSURE_2026-07-07.md"


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                rows.append(parsed)
    except (OSError, json.JSONDecodeError):
        return rows
    return rows


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
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _day(value: Any) -> str:
    text = str(value or "")[:10]
    return text if re.match(r"^\d{4}-\d{2}-\d{2}$", text) else ""


def _trade_day(trade: dict[str, Any]) -> str:
    for key in ("exit_date", "closed_at", "entry_date", "opened_at"):
        day = _day(trade.get(key))
        if day:
            return day
    return ""


def _postmortem_by_trade(path: Path, day: str) -> dict[str, dict[str, Any]]:
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or str(payload.get("date")) != day:
        return {}
    rows = payload.get("postmortems") if isinstance(payload.get("postmortems"), list) else []
    return {
        str(row.get("trade_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("trade_id")
    }


def _capture_efficiency_from_trade(trade: dict[str, Any]) -> dict[str, Any]:
    entry = _safe_float(trade.get("entry_price"))
    exit_price = _safe_float(trade.get("exit_price"))
    exit_return = ((exit_price / entry) - 1.0) * 100 if entry > 0 and exit_price > 0 else None
    best = trade.get("best_pnl_pct")
    best_pnl = _safe_float(best) if best not in (None, "") else exit_return
    return classify_exit_quality(best_pnl, exit_return, trade.get("exit_reason"))


def _classify_loop_state(pnl: float, quality: dict[str, Any]) -> str:
    capture = quality.get("capture_efficiency")
    giveback = quality.get("giveback_pct")
    if pnl < 0:
        return "entry_filter_review"
    if giveback is not None and _safe_float(giveback) >= 25:
        return "lesson_needed"
    if capture is not None and _safe_float(capture) < 0.5:
        return "lesson_needed"
    return "closed_clean"


def _loss_action_is_appropriate(action: Any) -> bool:
    text = str(action or "").strip().lower()
    if not text:
        return False
    contradictory = ("profit-capture", "profit capture", "ratchet", "winner faded", "runner giveback")
    return not any(phrase in text for phrase in contradictory)


def _lesson_for_trade(pnl: float, quality: dict[str, Any], explanation: dict[str, Any]) -> str:
    action = explanation.get("next_action")
    if pnl < 0:
        return str(action) if _loss_action_is_appropriate(action) else _default_lesson(pnl, quality)
    return str(action or _default_lesson(pnl, quality))


def _flip_trade_explanations(path: Path, postmortem_path: Path, day: str) -> list[dict[str, Any]]:
    trades = _read_json(path, [])
    if not isinstance(trades, list):
        return []
    postmortems = _postmortem_by_trade(postmortem_path, day)
    rows: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict) or trade.get("status") != "closed" or _trade_day(trade) != day:
            continue
        pm = postmortems.get(str(trade.get("id")), {})
        explanation = pm.get("pnl_explanation") if isinstance(pm.get("pnl_explanation"), dict) else {}
        observed_quality = _capture_efficiency_from_trade(trade)
        reported_quality = explanation.get("exit_quality") if isinstance(explanation.get("exit_quality"), dict) else {}
        quality = {**reported_quality, **observed_quality}
        pnl = round(_safe_float(trade.get("pnl")), 2)
        rows.append({
            "bot": "flip_bot",
            "trade_id": trade.get("id"),
            "date": day,
            "symbol": trade.get("symbol"),
            "strategy": trade.get("strategy"),
            "direction": trade.get("right"),
            "option_symbol": trade.get("option_symbol"),
            "contracts": _safe_int(trade.get("contracts")),
            "pnl": pnl,
            "entry_reason": trade.get("catalyst"),
            "exit_reason": trade.get("exit_reason"),
            "primary_driver": explanation.get("primary_driver") or _infer_primary_driver(pnl, trade.get("exit_reason")),
            "exit_quality": quality,
            "lesson": _lesson_for_trade(pnl, quality, explanation),
            "loop_state": _classify_loop_state(pnl, quality),
        })
    return rows


def _infer_primary_driver(pnl: float, exit_reason: Any) -> str:
    reason = str(exit_reason or "").lower()
    if pnl < 0:
        return "trade moved against the option until stop or guard exit"
    if "profit protect" in reason:
        return "trade went profitable, then faded into profit protection"
    if "profit target" in reason:
        return "trade reached profit target"
    return "trade closed with realized outcome from ledger"


def _default_lesson(pnl: float, quality: dict[str, Any]) -> str:
    if pnl < 0:
        return "review entry filter and regime conflict before next same-direction trade"
    if _safe_float(quality.get("giveback_pct")) >= 25:
        return "tighten profit-capture cadence or ratchet rules for similar runners"
    return "keep current exit handling under observation"


def _parse_credit_pnl(trade: dict[str, Any]) -> float | None:
    if trade.get("pnl") not in (None, ""):
        return round(_safe_float(trade.get("pnl")), 2)
    reason = str(trade.get("closing_reason") or "")
    credit = _safe_float(trade.get("net_credit"))
    qty = _safe_float(trade.get("qty"), 1.0)
    match = re.search(r"([+-]?\d+(?:\.\d+)?)% of credit", reason)
    if credit <= 0 or not match:
        return None
    return round(credit * qty * 100 * _safe_float(match.group(1)) / 100, 2)


def _options_trade_explanations(path: Path, postmortem_path: Path, day: str) -> list[dict[str, Any]]:
    payload = _read_json(path, {})
    trades = payload.get("trades") if isinstance(payload, dict) and isinstance(payload.get("trades"), list) else []
    trades = dedupe_options_trade_records(trades)
    postmortems = _postmortem_by_trade(postmortem_path, day)
    rows: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict) or trade.get("status") != "closed" or _trade_day(trade) != day:
            continue
        confidence = trade.get("candidate_confidence") if isinstance(trade.get("candidate_confidence"), dict) else {}
        pnl = _parse_credit_pnl(trade)
        pm = postmortems.get(str(trade.get("id")), {})
        explanation = pm.get("pnl_explanation") if isinstance(pm.get("pnl_explanation"), dict) else {}
        numeric_pnl = _safe_float(pnl) if pnl is not None else -0.01
        quality = {
            "credit_received": trade.get("net_credit"),
            "profit_close_pct": trade.get("profit_close_pct"),
            "stop_loss_pct": trade.get("stop_loss_pct"),
        }
        rows.append({
            "bot": "iwm_options_bot",
            "trade_id": trade.get("id"),
            "date": day,
            "symbol": trade.get("underlying"),
            "strategy": trade.get("strategy"),
            "direction": "credit_spread",
            "option_symbol": trade.get("label"),
            "contracts": _safe_int(trade.get("qty"), 1),
            "pnl": pnl,
            "entry_reason": "; ".join(str(r) for r in confidence.get("reasons", [])) if isinstance(confidence.get("reasons"), list) else "candidate_passed_all_filters",
            "exit_reason": trade.get("closing_reason"),
            "primary_driver": explanation.get("primary_driver") or "credit spread closed by stored close reason",
            "exit_quality": quality,
            "lesson": _lesson_for_trade(numeric_pnl, quality, explanation) if explanation else "compare credit/risk, DTE, trend filter, and realized close reason",
            "loop_state": "closed_clean" if pnl is not None and pnl >= 0 else "entry_filter_review",
        })
    return rows


def _lesson_id(row: dict[str, Any]) -> str:
    identity = {
        "date": row.get("date"),
        "bot": row.get("bot"),
        "trade_id": row.get("trade_id"),
        "loop_state": row.get("loop_state"),
    }
    canonical = json.dumps(identity, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def canonical_lessons(report: dict[str, Any]) -> list[dict[str, Any]]:
    generated_at = report.get("generated_at")
    lessons: list[dict[str, Any]] = []
    for row in report.get("trade_explanations", []):
        if not isinstance(row, dict) or not row.get("lesson"):
            continue
        state = str(row.get("loop_state") or "closed_clean")
        open_lesson = state in {"entry_filter_review", "lesson_needed"}
        lessons.append({
            "lesson_id": _lesson_id(row),
            "created_at": generated_at,
            "date": row.get("date"),
            "bot": row.get("bot"),
            "trade_id": row.get("trade_id"),
            "symbol": row.get("symbol"),
            "strategy": row.get("strategy"),
            "direction": row.get("direction"),
            "pnl": row.get("pnl"),
            "primary_driver": row.get("primary_driver"),
            "lesson": row.get("lesson"),
            "lesson_type": "entry_failure" if state == "entry_filter_review" else "exit_capture" if state == "lesson_needed" else "positive_reinforcement",
            "severity": "high" if state == "entry_filter_review" else "medium" if state == "lesson_needed" else "info",
            "status": "open" if open_lesson else "observed",
            "requires_counterfactual": open_lesson,
            "promotion_authority": "none",
            "next_stage": "counterfactual_shadow_trial" if open_lesson else "monitor_recurrence",
        })
    return lessons


def write_lesson_ledger(
    report: dict[str, Any],
    ledger_path: Path = LESSON_LEDGER_PATH,
    report_path: Path = LESSON_REPORT_PATH,
) -> dict[str, Any]:
    existing = _read_jsonl(ledger_path)
    existing_ids = {str(row.get("lesson_id")) for row in existing if row.get("lesson_id")}
    incoming = canonical_lessons(report)
    new_rows = [row for row in incoming if row["lesson_id"] not in existing_ids]
    if new_rows:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    all_rows = existing + new_rows
    payload = {
        "provider": "trade_lesson_ledger",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lesson_count": len(all_rows),
        "open_count": sum(1 for row in all_rows if row.get("status") == "open"),
        "new_count": len(new_rows),
        "lessons": all_rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _no_trade_explanations(path: Path, day: str) -> list[dict[str, Any]]:
    rows = [row for row in _read_jsonl(path) if _day(row.get("ts")) == day and row.get("action") == "skip"]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("symbol") or "unknown"), str(row.get("strategy") or "unknown"))].append(row)
    output: list[dict[str, Any]] = []
    for (symbol, strategy), items in sorted(grouped.items()):
        counts = Counter(str(item.get("reason") or "unknown") for item in items)
        primary, count = counts.most_common(1)[0]
        output.append({
            "bot": "iwm_options_bot",
            "date": day,
            "symbol": symbol,
            "strategy": strategy,
            "action": "skip",
            "primary_reason": primary,
            "count": count,
            "all_reasons": dict(counts),
            "latest_ts": max(str(item.get("ts") or "") for item in items),
            "explanation": _reason_explanation(primary),
        })
    return output


def _reason_explanation(reason: str) -> str:
    mapping = {
        "underlying_exposure_cap": "bot already had enough exposure to that underlying",
        "trend_filter_below_20sma": "trend filter rejected the put-spread setup",
        "credit_to_risk_below_minimum": "premium was not rich enough for the risk",
        "per_run_symbol_trade_cap": "one setup already used the per-run symbol slot",
        "market_closed": "market was closed",
        "iv_rank_below_minimum": "implied volatility was too low for premium selling",
    }
    return mapping.get(reason, "skip reason came from the bot decision log")


def _promotion_scoreboard(
    grades_path: Path,
    cheap_asymmetry_path: Path,
    learning_path: Path,
) -> list[dict[str, Any]]:
    grades = _read_json(grades_path, {})
    cheap = _read_json(cheap_asymmetry_path, {})
    learning = _read_json(learning_path, {})
    items = grades.get("items") if isinstance(grades, dict) and isinstance(grades.get("items"), list) else []
    goal_matches = _safe_int((cheap.get("summary") or {}).get("goal_match_count")) if isinstance(cheap, dict) else 0
    high_lessons = [
        row for row in (learning.get("lessons") if isinstance(learning, dict) and isinstance(learning.get("lessons"), list) else [])
        if isinstance(row, dict) and row.get("severity") in {"high", "critical"}
    ]

    scoreboard: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        sample_count = _safe_int(item.get("sample_count"))
        signal_count = _safe_int(item.get("signal_count"))
        evidence = _safe_float(item.get("evidence_score"))
        blockers: list[str] = []
        if sample_count < 10:
            blockers.append("needs_10_samples")
        if signal_count < 10 and item.get("category") in {"shadow_strategy", "context_scanner"}:
            blockers.append("needs_10_signal_events")
        if "Cheap Asymmetry" in name and goal_matches <= 0:
            blockers.append("no_repeated_goal_matches")
        if high_lessons and name in {"Cheap Asymmetry Scanner", "Flip Shadow Candidates", "Flip Bot"}:
            blockers.append("unresolved_high_severity_lessons")
        if item.get("promotion_ready") and not blockers:
            state = "review_candidate"
        elif evidence >= 70 and sample_count >= 10 and not blockers:
            state = "near_review"
        else:
            state = "blocked"
        close_score = min(100.0, evidence + min(sample_count, 30) * 0.5 + min(signal_count, 10))
        scoreboard.append({
            "name": name,
            "category": item.get("category"),
            "grade": item.get("grade"),
            "ops_grade": item.get("ops_grade"),
            "sample_count": sample_count,
            "signal_count": signal_count,
            "evidence_score": round(evidence, 1),
            "close_to_live_score": round(close_score, 1),
            "promotion_state": state,
            "blockers": blockers or list(item.get("warnings") or [])[:3],
            "note": "review still requires promotion rules, dual review, and explicit Kenny approval",
        })
    scoreboard.sort(key=lambda row: (row["promotion_state"] == "review_candidate", row["close_to_live_score"]), reverse=True)
    return scoreboard[:20]


def _next_day_gate(
    trade_explanations: list[dict[str, Any]],
    no_trades: list[dict[str, Any]],
    scoreboard: list[dict[str, Any]],
    learning_path: Path,
) -> dict[str, Any]:
    learning = _read_json(learning_path, {})
    lessons = learning.get("lessons") if isinstance(learning, dict) and isinstance(learning.get("lessons"), list) else []
    high_lessons = [row for row in lessons if isinstance(row, dict) and row.get("severity") in {"high", "critical"}]
    blockers: list[str] = []
    if high_lessons:
        blockers.append("unresolved_high_severity_lessons")
    if any(row.get("loop_state") == "entry_filter_review" for row in trade_explanations):
        blockers.append("entry_filter_review_required")
    if not any(row.get("promotion_state") == "review_candidate" for row in scoreboard):
        blockers.append("no_scanner_ready_for_promotion")
    return {
        "date": date.today().isoformat(),
        "can_promote_scanner": not blockers,
        "blockers": blockers,
        "must_review": [
            "Every trade has P/L explanation",
            "Every skip has a primary no-trade reason",
            "Every scanner has promotion blockers or review state",
            "Any rule change still requires tests and explicit approval",
        ],
        "tomorrow_focus": _tomorrow_focus(trade_explanations, no_trades, scoreboard, high_lessons),
    }


def _tomorrow_focus(
    trade_explanations: list[dict[str, Any]],
    no_trades: list[dict[str, Any]],
    scoreboard: list[dict[str, Any]],
    high_lessons: list[dict[str, Any]],
) -> str:
    if high_lessons:
        return "Resolve high-severity Flip lessons before promotion discussion."
    if any(row.get("loop_state") == "entry_filter_review" for row in trade_explanations):
        return "Review losing entries and require stronger fresh confirmation."
    if no_trades:
        return "Compare skip reasons against missed runners to decide whether filters are too strict."
    top = scoreboard[0]["name"] if scoreboard else "shadow scanners"
    return f"Collect another evidence day for {top}."


def build_report(
    day: str | None = None,
    *,
    flip_trades_path: Path = FLIP_TRADES_PATH,
    postmortem_path: Path = POSTMORTEM_PATH,
    options_trades_path: Path = OPTIONS_TRADES_PATH,
    options_decisions_path: Path = OPTIONS_DECISIONS_PATH,
    grades_path: Path = GRADES_PATH,
    cheap_asymmetry_path: Path = CHEAP_ASYMMETRY_PATH,
    learning_path: Path = LEARNING_PATH,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    trades = _flip_trade_explanations(flip_trades_path, postmortem_path, day)
    trades.extend(_options_trade_explanations(options_trades_path, postmortem_path, day))
    no_trades = _no_trade_explanations(options_decisions_path, day)
    scoreboard = _promotion_scoreboard(grades_path, cheap_asymmetry_path, learning_path)
    next_gate = _next_day_gate(trades, no_trades, scoreboard, learning_path)
    pnl_values = [row.get("pnl") for row in trades if row.get("pnl") not in (None, "")]
    total_pnl = round(sum(_safe_float(value) for value in pnl_values), 2)
    return {
        "provider": "loop_closure_report",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "trade_explanation_count": len(trades),
            "no_trade_count": len(no_trades),
            "promotion_score_count": len(scoreboard),
            "closed_trade_pnl": total_pnl,
            "lesson_needed_count": sum(1 for row in trades if row.get("loop_state") == "lesson_needed"),
            "entry_review_count": sum(1 for row in trades if row.get("loop_state") == "entry_filter_review"),
            "open_lesson_count": sum(1 for row in trades if row.get("loop_state") in {"lesson_needed", "entry_filter_review"}),
        },
        "chain": "scanner -> decision -> trade/no-trade -> exit quality -> P/L explanation -> lesson -> next-day gate",
        "trade_explanations": trades,
        "no_trade_explanations": no_trades,
        "promotion_scoreboard": scoreboard,
        "next_day_gate": next_gate,
        "warnings": [
            "Read-only loop report. No broker calls, no orders, no risk setting changes.",
            "Scanner review_candidate is not live-trading approval.",
            "Rule changes still require tests, execution audit, dual review, and explicit Kenny approval.",
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
    gate = report["next_day_gate"]
    lines = [
        "# Claude Code Handoff - Loop Closure Report",
        "",
        f"Date: {report['date']}",
        f"Generated: {report['generated_at']}",
        "",
        "## Objective",
        "",
        "Tighten the Vibe-Trading learning loop so every day has a durable scanner -> decision -> trade/no-trade -> exit quality -> P/L explanation -> lesson -> next-day gate chain.",
        "",
        "## Current Summary",
        "",
        f"- Trade explanations: {report['summary']['trade_explanation_count']}",
        f"- No-trade explanations: {report['summary']['no_trade_count']}",
        f"- Promotion rows: {report['summary']['promotion_score_count']}",
        f"- Closed trade P/L represented: {report['summary']['closed_trade_pnl']}",
        f"- Next-day promotion allowed: {gate['can_promote_scanner']}",
        "",
        "## Next-Day Gate Blockers",
        "",
    ]
    blockers = gate.get("blockers") if isinstance(gate.get("blockers"), list) else []
    lines.extend(f"- {blocker}" for blocker in blockers) if blockers else lines.append("- None.")
    lines.extend([
        "",
        "## Claude Task",
        "",
        "Review the loop-closure report, then improve the weakest missing explanations without changing execution behavior.",
        "",
        "## Commands",
        "",
        "```powershell",
        "python scripts\\loop_closure_report.py --print",
        "python scripts\\generate_dashboard.py",
        "python scripts\\execution_gate_audit.py --fail-on-issues --print",
        "python -m pytest agent\\tests\\test_loop_closure_report.py -q",
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    gate = report["next_day_gate"]
    print("\nLoop Closure Report | read-only")
    print("=" * 80)
    print(
        f"date={report['date']} trades={summary['trade_explanation_count']} "
        f"skips={summary['no_trade_count']} pnl=${summary['closed_trade_pnl']:.2f} "
        f"lesson_needed={summary['lesson_needed_count']} entry_reviews={summary['entry_review_count']}"
    )
    print(f"next_gate_promote={gate['can_promote_scanner']} blockers={gate['blockers']}")
    for row in report["trade_explanations"][:8]:
        print(f"- {row['bot']} {row.get('symbol')} pnl={row.get('pnl')} state={row.get('loop_state')} :: {row.get('lesson')}")
    for row in report["no_trade_explanations"][:8]:
        print(f"- skip {row.get('symbol')} {row.get('strategy')}: {row.get('primary_reason')} x{row.get('count')}")
    print(f"JSON: {REPORT_PATH}")
    print(f"Handoff: {HANDOFF_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only loop closure report.")
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
        write_lesson_ledger(report)
        write_handoff(report, args.handoff_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Loop closure report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
