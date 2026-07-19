"""Read-only outcome report for point-in-time 0DTE entry features."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.flip_shadow_pnl_evaluator import RESEARCH_ONLY_STRATEGIES, _read_jsonl, _row_key, evaluate_group
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from flip_shadow_pnl_evaluator import RESEARCH_ONLY_STRATEGIES, _read_jsonl, _row_key, evaluate_group

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "zero-dte-entry-feature-edge.json"
MIN_BUCKET_TRADES = 30
MIN_TRADING_DAYS = 10


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _numeric_bucket(value: Any, low: float, high: float, labels: tuple[str, str, str]) -> str:
    number = _number(value)
    if number is None:
        return "unavailable"
    if number < low:
        return labels[0]
    if number <= high:
        return labels[1]
    return labels[2]


def _time_bucket(value: Any) -> str:
    text = str(value or "")[:5]
    if not text:
        return "unavailable"
    return "lunch_1200_to_1330" if "12:00" <= text <= "13:30" else "outside_lunch"


def _regime(feature: dict[str, Any]) -> str:
    for key in ("rv_iv_regime", "volatility_regime", "trend_range_regime", "primary_regime"):
        value = feature.get(key)
        if value not in (None, "", "unknown", "unavailable"):
            return str(value)
    return "unavailable"


def _summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(trade.get("evidence_exit_return_pct") or 0.0) for trade in trades]
    days = {str(trade.get("date") or "")[:10] for trade in trades if trade.get("date")}
    wins = [value for value in returns if value > 0]
    count = len(returns)
    promotion_grade = sum(1 for trade in trades if trade.get("executable_quote_coverage") is True)
    sufficient = count >= MIN_BUCKET_TRADES and len(days) >= MIN_TRADING_DAYS
    return {
        "completed_count": count,
        "trading_day_count": len(days),
        "win_rate": round(len(wins) / count, 3) if count else 0.0,
        "expectancy_return_pct": round(sum(returns) / count, 2) if count else 0.0,
        "promotion_grade_quote_count": promotion_grade,
        "evidence_status": "eligible_for_review" if sufficient else "insufficient_forward_evidence",
    }


def _dimension(
    trades: list[dict[str, Any]], classifier: Callable[[dict[str, Any]], str]
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[classifier(trade)].append(trade)
    return {key: _summary(value) for key, value in sorted(groups.items())}


def build_report(log_path: Path = LOG_PATH) -> dict[str, Any]:
    rows = [
        row for row in _read_jsonl(log_path)
        if int(row.get("schema_version") or 0) >= 3
        and row.get("data_quality") == "current_session_lifecycle"
        and row.get("execution_mode") == "shadow_only"
        and str(row.get("strategy") or "") not in RESEARCH_ONLY_STRATEGIES
    ]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("symbol") and row.get("option_symbol"):
            groups[_row_key(row)].append(row)
    trades = [evaluate_group(group) for group in groups.values()]
    completed = [trade for trade in trades if trade.get("status") in {"winner", "loser"}]

    def feature(trade: dict[str, Any]) -> dict[str, Any]:
        value = trade.get("feature_snapshot")
        return value if isinstance(value, dict) else {}

    opening = lambda trade: _numeric_bucket(
        feature(trade).get("opening_range_fraction"), 0.20, 0.45,
        ("compressed_under_20pct", "balanced_20_to_45pct", "expanded_over_45pct"),
    )
    consumed = lambda trade: _numeric_bucket(
        feature(trade).get("expected_move_consumed_fraction"), 0.50, 1.00,
        ("under_50pct", "50_to_100pct", "over_100pct"),
    )
    atr = lambda trade: _numeric_bucket(
        feature(trade).get("orb_breakout_candle_atr_ratio"), 0.80, 1.20,
        ("under_0_8_atr", "0_8_to_1_2_atr", "over_1_2_atr"),
    )
    return {
        "provider": "zero_dte_entry_feature_edge_report",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(log_path),
        "completed_lifecycle_count": len(completed),
        "minimum_bucket_trades": MIN_BUCKET_TRADES,
        "minimum_trading_days": MIN_TRADING_DAYS,
        "by_entry_time": _dimension(completed, lambda trade: _time_bucket(trade.get("episode_bucket_et"))),
        "by_breakout_atr": _dimension(completed, atr),
        "by_opening_range_fraction": _dimension(completed, opening),
        "by_expected_move_consumed": _dimension(completed, consumed),
        "by_regime": _dimension(completed, lambda trade: _regime(feature(trade))),
        "opening_range_x_consumed": _dimension(completed, lambda trade: f"{opening(trade)}|{consumed(trade)}"),
        "regime_x_opening_range": _dimension(
            completed, lambda trade: f"{_regime(feature(trade))}|{opening(trade)}"
        ),
        "warnings": [
            "Research telemetry only; this report cannot change execution behavior.",
            "Unavailable point-in-time fields remain unavailable and are never reconstructed from future data.",
            "Bucket results are exploratory until minimum samples, chronological holdout, and multiple-testing review pass.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.log_path)
    write_report(report, args.report_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"0DTE entry feature report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
