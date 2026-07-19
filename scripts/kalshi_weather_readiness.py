#!/usr/bin/env python3
"""Fail-closed readiness gate for a future Kalshi weather order adapter."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME = Path.home() / ".vibe-trading"
PERFORMANCE_PATH = RUNTIME / "reports" / "kalshi-weather-performance.json"
BOT_REPORT_PATH = RUNTIME / "reports" / "kalshi-weather-bot.json"
REPORT_PATH = RUNTIME / "reports" / "kalshi-weather-readiness.json"

MIN_CLOSED = 200
MIN_TARGET_DATES = 14
MIN_PROFIT_FACTOR = 1.25
MAX_DRAWDOWN_ON_RISK = 0.25
MAX_BRIER = 0.20
MIN_BRIER_SKILL = 0.01


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_report(
    *,
    performance_path: Path = PERFORMANCE_PATH,
    bot_report_path: Path = BOT_REPORT_PATH,
    authenticated_adapter_reviewed: bool = False,
) -> dict[str, Any]:
    performance = _read(performance_path)
    bot = _read(bot_report_path)
    metrics = performance.get("metrics") if isinstance(performance.get("metrics"), dict) else {}
    calibration = performance.get("calibration") if isinstance(performance.get("calibration"), dict) else {}
    closed = int(performance.get("promotion_grade_closed_count") or 0)
    dates = int(performance.get("distinct_target_dates") or 0)
    brier = calibration.get("model_brier_score")
    brier_skill = calibration.get("brier_skill_vs_market")
    checks = {
        "promotion_grade_closures": {"passed": closed >= MIN_CLOSED, "observed": closed, "minimum": MIN_CLOSED},
        "target_dates": {"passed": dates >= MIN_TARGET_DATES, "observed": dates, "minimum": MIN_TARGET_DATES},
        "positive_net_pnl": {"passed": float(metrics.get("net_pnl_dollars") or 0.0) > 0, "observed": metrics.get("net_pnl_dollars")},
        "profit_factor": {"passed": float(metrics.get("profit_factor") or 0.0) >= MIN_PROFIT_FACTOR, "observed": metrics.get("profit_factor"), "minimum": MIN_PROFIT_FACTOR},
        "drawdown": {"passed": metrics.get("drawdown_on_risk") is not None and float(metrics["drawdown_on_risk"]) <= MAX_DRAWDOWN_ON_RISK, "observed": metrics.get("drawdown_on_risk"), "maximum": MAX_DRAWDOWN_ON_RISK},
        "model_brier": {"passed": brier is not None and float(brier) <= MAX_BRIER, "observed": brier, "maximum": MAX_BRIER},
        "model_skill": {"passed": brier_skill is not None and float(brier_skill) >= MIN_BRIER_SKILL, "observed": brier_skill, "minimum": MIN_BRIER_SKILL},
        "series_coverage": {"passed": int(bot.get("events_discovered") or 0) >= int(bot.get("series_monitored") or 13), "observed": bot.get("events_discovered"), "expected": bot.get("series_monitored", 13)},
        "latest_scan_clean": {"passed": not (bot.get("errors") or []), "observed_errors": bot.get("errors") or []},
        "authenticated_adapter_reviewed": {"passed": bool(authenticated_adapter_reviewed)},
    }
    blocker_map = {
        "promotion_grade_closures": "insufficient_promotion_grade_closures",
        "target_dates": "insufficient_target_dates",
        "positive_net_pnl": "non_positive_net_pnl",
        "profit_factor": "profit_factor_below_minimum",
        "drawdown": "drawdown_above_maximum",
        "model_brier": "model_calibration_below_standard",
        "model_skill": "model_does_not_beat_market_calibration",
        "series_coverage": "weather_series_coverage_incomplete",
        "latest_scan_clean": "latest_scan_has_errors",
        "authenticated_adapter_reviewed": "authenticated_order_adapter_not_reviewed",
    }
    blockers = [blocker_map[name] for name, check in checks.items() if not check["passed"]]
    evidence_names = [name for name in checks if name != "authenticated_adapter_reviewed"]
    return {
        "provider": "kalshi_weather_readiness",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "evidence_ready": all(checks[name]["passed"] for name in evidence_names),
        "go_live_eligible": not blockers,
        "requires_explicit_human_enablement": True,
        "checks": checks,
        "blockers": blockers,
        "warnings": [
            "This report cannot submit orders or enable authenticated execution.",
            "Passing sample count alone is insufficient; profitability, drawdown, calibration, and market-relative skill must all pass.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--performance-path", type=Path, default=PERFORMANCE_PATH)
    parser.add_argument("--bot-report-path", type=Path, default=BOT_REPORT_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--adapter-reviewed", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(
        performance_path=args.performance_path,
        bot_report_path=args.bot_report_path,
        authenticated_adapter_reviewed=args.adapter_reviewed,
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True) if args.print_report else f"Kalshi weather readiness written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
