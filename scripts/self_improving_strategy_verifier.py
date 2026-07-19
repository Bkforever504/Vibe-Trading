#!/usr/bin/env python3
"""Read-only verifier for self-improving trading strategy loops.

This is the local Horizon/TensorTrade-inspired maker-checker layer:
candidate generators may propose strategies, but this verifier scores them
from independent evidence before anything can become a promotion candidate.
It never calls a broker, never changes bot configuration, and never approves
live trading by itself.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "self-improving-strategy-verifier.json"
LOG_PATH = ROOT / "data" / "self_improving_strategy_verifier_log.jsonl"

SHADOW_EVAL_PATH = REPORT_DIR / "flip-shadow-pnl-evaluator.json"
HOT_INSTRUMENT_PATH = REPORT_DIR / "weekly-hot-instruments.json"
LOOP_READINESS_PATH = REPORT_DIR / "loop-readiness-audit.json"
INCENTIVE_SAFETY_PATH = REPORT_DIR / "agent-incentive-safety-audit.json"
KRONOS_FORECAST_PATH = REPORT_DIR / "kronos-market-forecast.json"

MIN_COMPLETED_TRADES = 10
MIN_TRADING_DAYS = 30
MIN_EXPECTANCY_RETURN_PCT = 1.0
MAX_AVG_LOSS_TO_WIN_RATIO = 1.25
MIN_VERIFIER_SCORE = 80.0
HUMAN_PROMOTION_REVIEW_SCORE = 90.0


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> float:
    return round(value, 3)


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _shadow_by_symbol(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_symbol = report.get("by_symbol")
    if not isinstance(by_symbol, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for symbol, stats in by_symbol.items():
        if isinstance(stats, dict):
            normalized[_normalize_symbol(symbol)] = stats
    return normalized


def _hot_by_symbol(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: list[Any] = []
    for key in (
        "hot_instruments",
        "manual_social_instruments",
        "verifier_instruments",
        "candidates",
        "items",
        "symbols",
    ):
        value = report.get(key)
        if isinstance(value, list):
            rows.extend(value)
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _normalize_symbol(row.get("symbol"))
        if symbol:
            normalized[symbol] = row
    return normalized


def _kronos_by_symbol(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("forecasts") or report.get("items") or []
    if not isinstance(rows, list):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _normalize_symbol(row.get("symbol"))
        if symbol:
            normalized[symbol] = row
    return normalized


def _governance_summary(loop_report: dict[str, Any], safety_report: dict[str, Any]) -> dict[str, Any]:
    loop_pass = not bool(loop_report.get("summary", {}).get("unattended_ready_count"))
    safety_pass = bool(safety_report.get("passed", True))
    execution_capable = _safe_int(loop_report.get("summary", {}).get("execution_capable_count"))
    high_risk = _safe_int(safety_report.get("summary", {}).get("high_risk_count"))
    return {
        "loop_governance_passed": loop_pass,
        "incentive_safety_passed": safety_pass,
        "execution_capable_count": execution_capable,
        "high_risk_count": high_risk,
        "overall_passed": loop_pass and safety_pass and high_risk == 0,
    }


def _instrument_evidence(
    symbol: str,
    shadow: dict[str, Any],
    hot: dict[str, Any] | None,
    kronos: dict[str, Any] | None,
    governance: dict[str, Any],
) -> dict[str, Any]:
    completed = _safe_int(shadow.get("completed_count"))
    sample_count = _safe_int(shadow.get("sample_count"))
    trading_days = _safe_int(shadow.get("trading_day_count"))
    required_completed = max(1, _safe_int(shadow.get("required_completed_count"), MIN_COMPLETED_TRADES))
    required_trading_days = max(1, _safe_int(shadow.get("required_trading_day_count"), MIN_TRADING_DAYS))
    required_oos = max(1, _safe_int(shadow.get("required_out_of_sample_count"), 5))
    out_of_sample_count = _safe_int(shadow.get("out_of_sample_count"))
    out_of_sample_positive = bool(shadow.get("out_of_sample_positive"))
    has_oos_evidence = "out_of_sample_count" in shadow or "required_out_of_sample_count" in shadow
    win_rate = _safe_float(shadow.get("win_rate"))
    expectancy = _safe_float(shadow.get("expectancy_return_pct"))
    avg_win = _safe_float(shadow.get("avg_win_return_pct"))
    avg_loss = _safe_float(shadow.get("avg_loss_return_pct"))
    target_hit_rate = _safe_float(shadow.get("target_hit_rate"))
    capture = _safe_float(shadow.get("avg_capture_efficiency"))
    payoff_ratio = _safe_float(shadow.get("payoff_ratio"))
    executable_quote_coverage = _safe_float(shadow.get("executable_quote_coverage_rate"), 1.0)
    accelerated_evidence = str(shadow.get("evidence_path") or "").startswith("accelerated_")

    score = 0.0
    blockers: list[str] = []
    reasons: list[str] = []
    memory_lessons: list[str] = []

    sample_score = min(20.0, completed / required_completed * 20.0)
    day_score = min(15.0, trading_days / required_trading_days * 15.0)
    expectancy_score = min(25.0, max(expectancy, 0.0) / 30.0 * 25.0)
    win_score = min(12.0, max(win_rate, 0.0) * 12.0)
    target_score = min(8.0, max(target_hit_rate, 0.0) * 8.0)
    capture_score = min(8.0, max(capture, 0.0) * 8.0)
    social_score = 0.0
    if hot:
        hot_score = _safe_float(hot.get("hot_score"), _safe_float(hot.get("score")))
        social_score = min(7.0, hot_score + _safe_int(hot.get("social_day_count")) * 0.5)
    model_score = 0.0
    if kronos:
        confidence = _safe_float(kronos.get("confidence"))
        expected_move = abs(_safe_float(kronos.get("expected_return_pct") or kronos.get("forecast_return_pct")))
        model_score = min(5.0, confidence * 3.0 + min(expected_move, 2.0))

    score = sample_score + day_score + expectancy_score + win_score + target_score + capture_score + social_score + model_score

    if completed < required_completed:
        blockers.append(f"needs_{required_completed}_completed_shadow_trades")
        memory_lessons.append("Do not promote from a small sample, even when early winners look attractive.")
    else:
        reasons.append("minimum completed shadow sample met")

    if trading_days < required_trading_days:
        blockers.append(f"needs_{required_trading_days}_trading_days")
        memory_lessons.append("Do not let clustered same-day signals masquerade as durable edge.")
    else:
        reasons.append("minimum trading-day diversity met")

    if expectancy < MIN_EXPECTANCY_RETURN_PCT:
        blockers.append("expectancy_not_positive_enough")
        memory_lessons.append("Win rate is not enough; average loss and payoff shape must preserve positive expectancy.")
    else:
        reasons.append("positive cost-adjusted exit expectancy" if accelerated_evidence else "positive simulated-exit expectancy")

    if accelerated_evidence and executable_quote_coverage < 1.0:
        blockers.append("incomplete_entry_ask_exit_bid_quote_coverage")
        memory_lessons.append("Midpoint shadow returns cannot support promotion; require complete executable bid/ask paths.")

    if has_oos_evidence and out_of_sample_count < required_oos:
        blockers.append(f"needs_{required_oos}_chronological_holdout_trades")
        memory_lessons.append("High intraday throughput cannot replace a sufficiently large chronological holdout.")
    elif has_oos_evidence and not out_of_sample_positive:
        blockers.append("chronological_holdout_expectancy_not_positive")
        memory_lessons.append("Do not promote a strategy whose newest holdout trades lost money.")
    elif has_oos_evidence:
        reasons.append("chronological holdout expectancy is positive")

    if avg_loss > 0 and avg_win > 0 and avg_loss > avg_win * MAX_AVG_LOSS_TO_WIN_RATIO:
        blockers.append("losses_too_large_vs_winners")
        memory_lessons.append("The classic retail failure is holding losers longer than winners; block promotion when payoff ratio degrades.")

    if not governance.get("overall_passed"):
        blockers.append("governance_or_incentive_safety_not_clean")

    if hot and str(hot.get("action") or "") == "research_only":
        blockers.append("instrument_research_only")
        memory_lessons.append("Social attention cannot override explicit liquidity, affordability, or noise vetoes.")

    if hot and hot.get("options_liquidity_checked") and not hot.get("options_execution_quality_ok"):
        blockers.append("options_execution_quality_failed")
        memory_lessons.append("Require an executable option chain before promotion review, not merely a liquid underlying.")

    if score < MIN_VERIFIER_SCORE:
        blockers.append("verifier_score_below_promotion_threshold")

    action = "reject_for_now"
    if blockers:
        action = "continue_shadow_memory"
    elif score >= HUMAN_PROMOTION_REVIEW_SCORE:
        action = "human_promotion_review_only"
    elif score >= MIN_VERIFIER_SCORE:
        action = "priority_shadow_review"

    return {
        "symbol": symbol,
        "verifier_score": round(score, 2),
        "action": action,
        "sample_count": sample_count,
        "completed_count": completed,
        "trading_day_count": trading_days,
        "evidence_path": shadow.get("evidence_path") or "legacy_daily_forward",
        "required_completed_count": required_completed,
        "required_trading_day_count": required_trading_days,
        "required_out_of_sample_count": required_oos,
        "out_of_sample_count": out_of_sample_count,
        "out_of_sample_positive": out_of_sample_positive,
        "win_rate": _pct(win_rate),
        "expectancy_return_pct": round(expectancy, 2),
        "avg_win_return_pct": round(avg_win, 2),
        "avg_loss_return_pct": round(avg_loss, 2),
        "payoff_ratio": round(payoff_ratio, 3) if payoff_ratio else None,
        "target_hit_rate": _pct(target_hit_rate),
        "avg_capture_efficiency": _pct(capture),
        "executable_quote_coverage_rate": round(executable_quote_coverage, 3),
        "hot_instrument_action": (hot or {}).get("action"),
        "kronos_regime": (kronos or {}).get("regime") or (kronos or {}).get("direction"),
        "score_components": {
            "sample": round(sample_score, 2),
            "trading_days": round(day_score, 2),
            "expectancy": round(expectancy_score, 2),
            "win_rate": round(win_score, 2),
            "target_hit_rate": round(target_score, 2),
            "capture_efficiency": round(capture_score, 2),
            "social_hotness": round(social_score, 2),
            "model_context": round(model_score, 2),
        },
        "promotion_blockers": blockers,
        "reasons": reasons,
        "memory_lessons": memory_lessons[:4],
        "live_execution_allowed": False,
    }


def build_report(
    *,
    shadow_eval_path: Path = SHADOW_EVAL_PATH,
    hot_instrument_path: Path = HOT_INSTRUMENT_PATH,
    loop_readiness_path: Path = LOOP_READINESS_PATH,
    incentive_safety_path: Path = INCENTIVE_SAFETY_PATH,
    kronos_forecast_path: Path = KRONOS_FORECAST_PATH,
    today: str | None = None,
) -> dict[str, Any]:
    today = today or date.today().isoformat()
    shadow_report = _read_json(shadow_eval_path)
    hot_report = _read_json(hot_instrument_path)
    loop_report = _read_json(loop_readiness_path)
    safety_report = _read_json(incentive_safety_path)
    kronos_report = _read_json(kronos_forecast_path)

    shadow = _shadow_by_symbol(shadow_report)
    hot = _hot_by_symbol(hot_report)
    kronos = _kronos_by_symbol(kronos_report)
    governance = _governance_summary(loop_report, safety_report)
    symbols = sorted(set(shadow) | set(hot))

    instruments = [
        _instrument_evidence(symbol, shadow.get(symbol, {}), hot.get(symbol), kronos.get(symbol), governance)
        for symbol in symbols
        if shadow.get(symbol) or hot.get(symbol)
    ]
    instruments.sort(key=lambda item: (item["verifier_score"], item["expectancy_return_pct"]), reverse=True)
    promotion_ready = [
        item for item in instruments
        if item["action"] == "human_promotion_review_only" and not item["promotion_blockers"]
    ]

    return {
        "provider": "self_improving_strategy_verifier",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "framework": {
            "generate": "Existing shadow scanners and candidate logs propose trades.",
            "evaluate": "Flip shadow P&L evaluator supplies path-aware simulated exits.",
            "select": "This verifier scores evidence and blocks self-approval.",
            "memory": "Failures and blockers are converted into reusable memory lessons.",
        },
        "thresholds": {
            "min_completed_trades": MIN_COMPLETED_TRADES,
            "min_trading_days": MIN_TRADING_DAYS,
            "min_expectancy_return_pct": MIN_EXPECTANCY_RETURN_PCT,
            "min_verifier_score": MIN_VERIFIER_SCORE,
        },
        "summary": {
            "instrument_count": len(instruments),
            "promotion_ready_count": len(promotion_ready),
            "priority_shadow_review_count": sum(1 for item in instruments if item["action"] == "priority_shadow_review"),
            "blocked_count": sum(1 for item in instruments if item["promotion_blockers"]),
            "governance_passed": governance["overall_passed"],
        },
        "governance": governance,
        "instruments": instruments,
        "promotion_ready": promotion_ready,
        "warnings": [
            "Read-only verifier. It cannot promote live execution.",
            "No strategy may score or approve its own work.",
            "TensorTrade/RL research belongs in shadow simulation until costs, slippage, and out-of-sample durability are proven.",
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


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("\nSelf-Improving Strategy Verifier | read-only")
    print("=" * 88)
    print(
        f"instruments={summary['instrument_count']} promotion_ready={summary['promotion_ready_count']} "
        f"priority_shadow={summary['priority_shadow_review_count']} blocked={summary['blocked_count']} "
        f"governance_passed={summary['governance_passed']}"
    )
    for item in report["instruments"][:10]:
        blockers = ",".join(item["promotion_blockers"][:3]) or "none"
        print(
            f"{item['symbol']:<6} score={item['verifier_score']:<6} action={item['action']:<26} "
            f"completed={item['completed_count']:<3} days={item['trading_day_count']:<3} "
            f"expectancy={item['expectancy_return_pct']:<7} blockers={blockers}"
        )
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only self-improving strategy verifier report.")
    parser.add_argument("--print", action="store_true", dest="print_report")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    report = build_report()
    write_report(report, args.report_path)
    if not args.no_log:
        append_log(report)
    if args.print_report:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
