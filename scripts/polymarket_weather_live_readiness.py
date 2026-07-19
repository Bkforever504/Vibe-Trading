#!/usr/bin/env python3
"""Evaluate weather-bot evidence and venue eligibility without enabling orders."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME = Path.home() / ".vibe-trading"
STATE_PATH = RUNTIME / "polymarket-weather-paper-state.json"
BOT_REPORT_PATH = RUNTIME / "reports" / "polymarket-weather-bot.json"
REPORT_PATH = RUNTIME / "reports" / "polymarket-weather-live-readiness.json"

MIN_PROMOTION_GRADE_CLOSURES = 200
MIN_DISTINCT_TARGET_DATES = 30
MIN_PROFIT_FACTOR = 1.25
MAX_DRAWDOWN_ON_RISK = 0.25


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _max_drawdown(pnls: list[float]) -> float:
    equity = peak = max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def build_report(
    *,
    state_path: Path = STATE_PATH,
    bot_report_path: Path = BOT_REPORT_PATH,
    order_adapter_reviewed: bool = False,
) -> dict[str, Any]:
    state = _read(state_path)
    bot = _read(bot_report_path)
    closed = [
        row for row in (state.get("closed_positions") or [])
        if isinstance(row, dict) and row.get("promotion_grade") is True and row.get("exit_reason")
    ]
    pnls = [float(row.get("pnl_dollars") or 0.0) for row in closed]
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    net_pnl = sum(pnls)
    total_risk = sum(float(row.get("risk_dollars") or 0.0) for row in closed)
    max_drawdown = _max_drawdown(pnls)
    drawdown_on_risk = max_drawdown / total_risk if total_risk else 1.0
    target_dates = {str(row.get("target_date")) for row in closed if row.get("target_date")}
    venue = bot.get("venue_eligibility") if isinstance(bot.get("venue_eligibility"), dict) else {}
    jurisdiction_allowed = bool(venue.get("checked") is True and venue.get("blocked") is False)
    scan_clean = not (bot.get("errors") or [])

    checks = {
        "jurisdiction_allowed": {"passed": jurisdiction_allowed, "observed": venue},
        "promotion_grade_closures": {"passed": len(closed) >= MIN_PROMOTION_GRADE_CLOSURES, "observed": len(closed), "minimum": MIN_PROMOTION_GRADE_CLOSURES},
        "distinct_target_dates": {"passed": len(target_dates) >= MIN_DISTINCT_TARGET_DATES, "observed": len(target_dates), "minimum": MIN_DISTINCT_TARGET_DATES},
        "positive_net_pnl": {"passed": net_pnl > 0, "observed": round(net_pnl, 2)},
        "profit_factor": {"passed": profit_factor >= MIN_PROFIT_FACTOR, "observed": None if profit_factor == float("inf") else round(profit_factor, 3), "minimum": MIN_PROFIT_FACTOR},
        "max_drawdown_on_risk": {"passed": drawdown_on_risk <= MAX_DRAWDOWN_ON_RISK, "observed": round(drawdown_on_risk, 4), "maximum": MAX_DRAWDOWN_ON_RISK},
        "latest_scan_clean": {"passed": scan_clean, "observed_errors": bot.get("errors") or []},
        "order_adapter_reviewed": {"passed": bool(order_adapter_reviewed)},
    }
    blocker_map = {
        "jurisdiction_allowed": "jurisdiction_blocked" if venue.get("blocked") is True else "jurisdiction_unverified",
        "promotion_grade_closures": "insufficient_promotion_grade_closures",
        "distinct_target_dates": "insufficient_distinct_target_dates",
        "positive_net_pnl": "non_positive_net_pnl",
        "profit_factor": "profit_factor_below_minimum",
        "max_drawdown_on_risk": "drawdown_above_maximum",
        "latest_scan_clean": "latest_scan_has_errors",
        "order_adapter_reviewed": "order_adapter_not_reviewed",
    }
    blockers = [blocker_map[name] for name, check in checks.items() if not check["passed"]]
    evidence_checks = [name for name in checks if name not in {"jurisdiction_allowed", "order_adapter_reviewed"}]
    return {
        "provider": "polymarket_weather_live_readiness",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "requires_explicit_human_enablement": True,
        "evidence_ready": all(checks[name]["passed"] for name in evidence_checks),
        "go_live_eligible": not blockers,
        "blockers": blockers,
        "checks": checks,
        "metrics": {
            "promotion_grade_closed_count": len(closed),
            "distinct_target_dates": len(target_dates),
            "net_pnl_dollars": round(net_pnl, 2),
            "gross_profit_dollars": round(gross_profit, 2),
            "gross_loss_dollars": round(gross_loss, 2),
            "profit_factor": None if profit_factor == float("inf") else round(profit_factor, 3),
            "max_drawdown_dollars": round(max_drawdown, 2),
            "total_risk_dollars": round(total_risk, 2),
        },
        "warnings": [
            "This report cannot enable trading or submit orders.",
            "Do not bypass Polymarket geographic restrictions.",
            "A calendar deadline cannot override failed evidence, jurisdiction, or technical checks.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--bot-report-path", type=Path, default=BOT_REPORT_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(state_path=args.state_path, bot_report_path=args.bot_report_path)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Polymarket weather live readiness written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
