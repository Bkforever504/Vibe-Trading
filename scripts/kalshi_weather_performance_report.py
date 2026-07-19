#!/usr/bin/env python3
"""Build event-level performance and calibration for Kalshi weather paper trades."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME = Path.home() / ".vibe-trading"
STATE_PATH = RUNTIME / "kalshi-weather-paper-state.json"
REPORT_PATH = RUNTIME / "reports" / "kalshi-weather-performance.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(row.get("pnl_dollars") or 0.0) for row in rows]
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    risk = sum(float(row.get("risk_dollars") or 0.0) for row in rows)
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    return {
        "closed_count": len(rows),
        "wins": sum(value > 0 for value in pnls),
        "win_rate": round(sum(value > 0 for value in pnls) / len(rows), 4) if rows else None,
        "net_pnl_dollars": round(sum(pnls), 2),
        "gross_profit_dollars": round(gross_profit, 2),
        "gross_loss_dollars": round(gross_loss, 2),
        "profit_factor": None if profit_factor == float("inf") else round(profit_factor, 3),
        "max_drawdown_dollars": round(_max_drawdown(pnls), 2),
        "total_risk_dollars": round(risk, 2),
        "drawdown_on_risk": round(_max_drawdown(pnls) / risk, 4) if risk else None,
        "expectancy_dollars": round(sum(pnls) / len(rows), 4) if rows else None,
    }


def build_report(state_path: Path = STATE_PATH) -> dict[str, Any]:
    state = _read(state_path)
    open_rows = [row for row in state.get("positions", []) if isinstance(row, dict)]
    closed = [
        row for row in state.get("closed_positions", [])
        if isinstance(row, dict) and row.get("promotion_grade") is True and row.get("exit_reason")
    ]
    model_errors: list[float] = []
    market_errors: list[float] = []
    for row in closed:
        outcome = 1.0 if row.get("won") is True else 0.0
        model = float(row.get("entry_fair_probability") or 0.0)
        market = float(row.get("entry_price") or 0.0)
        model_errors.append((model - outcome) ** 2)
        market_errors.append((market - outcome) ** 2)
    model_brier = sum(model_errors) / len(model_errors) if model_errors else None
    market_brier = sum(market_errors) / len(market_errors) if market_errors else None
    by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in closed:
        by_city[str(row.get("city") or "Unknown")].append(row)
    city_days = {(str(row.get("city") or ""), str(row.get("target_date") or "")) for row in closed}
    target_dates = {str(row.get("target_date")) for row in closed if row.get("target_date")}
    return {
        "provider": "kalshi_weather_performance_report",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "paper_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "open_count": len(open_rows),
        "promotion_grade_closed_count": len(closed),
        "distinct_city_days": len(city_days),
        "distinct_target_dates": len(target_dates),
        "metrics": _metrics(closed),
        "calibration": {
            "sample_count": len(model_errors),
            "model_brier_score": round(model_brier, 4) if model_brier is not None else None,
            "market_brier_score": round(market_brier, 4) if market_brier is not None else None,
            "brier_skill_vs_market": round(market_brier - model_brier, 4) if model_brier is not None and market_brier is not None else None,
        },
        "by_city": {city: _metrics(rows) for city, rows in sorted(by_city.items())},
        "warnings": [
            "Counts one selected city-day position as one independent observation.",
            "Brier skill must beat the executable market entry probability, not merely look accurate in isolation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.state_path)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True) if args.print_report else f"Kalshi weather performance written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
