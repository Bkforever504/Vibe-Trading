#!/usr/bin/env python3
"""Rank the daily Flip Bot options universe without changing execution."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
WEEKLY_PATH = REPORT_DIR / "weekly-hot-instruments.json"
LIQUIDITY_PATH = REPORT_DIR / "options-liquidity-feasibility.json"
SHADOW_PATH = REPORT_DIR / "flip-shadow-pnl-evaluator.json"
CATALYST_PATH = REPORT_DIR / "market-catalyst-calendar.json"
SURFACE_PATH = REPORT_DIR / "options-surface-intelligence.json"
REPORT_PATH = REPORT_DIR / "daily-options-universe-ranker.json"
LOG_PATH = ROOT / "data" / "daily_options_universe_ranker_log.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, default))


def _by_symbol(rows: list[Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def _shadow_by_symbol(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("by_symbol")
    if not isinstance(raw, dict):
        return {}
    return {
        str(symbol).upper(): values
        for symbol, values in raw.items()
        if isinstance(values, dict)
    }


def _rank_symbol(
    symbol: str,
    hot: dict[str, Any],
    liquidity: dict[str, Any],
    shadow: dict[str, Any],
    surface: dict[str, Any],
) -> dict[str, Any]:
    completed = _integer(shadow.get("completed_count"))
    trading_days = _integer(shadow.get("trading_day_count"))
    oos_count = _integer(shadow.get("out_of_sample_count"))
    expectancy = _number(shadow.get("out_of_sample_expectancy_return_pct"), _number(shadow.get("expectancy_return_pct")))
    win_rate = _number(shadow.get("out_of_sample_win_rate"), _number(shadow.get("win_rate")))
    oos_positive = bool(shadow.get("out_of_sample_positive"))
    promotion_eligible = bool(shadow.get("promotion_eligible"))
    liquidity_score = _number(liquidity.get("score"))
    liquidity_ok = bool(liquidity.get("flip_shadow_eligible"))
    surface_ok = str(surface.get("status") or "") == "ok"
    surface_usable = bool(surface.get("surface_usable_for_shadow_research"))
    retail_lottery_risk = bool(surface.get("retail_lottery_risk"))

    blockers: list[str] = []
    if not liquidity:
        blockers.append("options_chain_not_checked")
    else:
        if str(liquidity.get("status") or "ok") != "ok":
            blockers.append("options_chain_unavailable")
        if not liquidity_ok:
            blockers.append("options_liquidity_gate_failed")
    if completed < 10:
        blockers.append("fewer_than_10_completed_shadow_lifecycles")
    if trading_days < 30:
        blockers.append("fewer_than_30_shadow_trading_days")
    if not oos_positive:
        blockers.append("positive_out_of_sample_edge_not_proven")
    if retail_lottery_risk:
        blockers.append("cheap_option_retail_lottery_risk")

    score = min(25.0, liquidity_score / 5.0 * 25.0)
    if liquidity_ok:
        score += 5.0
    score += min(10.0, _number(hot.get("hot_score")) / 12.0 * 10.0)
    score += min(8.0, _number(hot.get("deep_universe_score")) / 10.0 * 8.0)
    score += min(8.0, completed / 10.0 * 8.0)
    score += min(7.0, trading_days / 30.0 * 7.0)
    if surface_usable:
        score += 5.0
    if retail_lottery_risk:
        score -= 15.0
    if oos_positive and expectancy > 0:
        score += min(6.0, 2.0 + expectancy / 10.0)
    if oos_count >= 10 and win_rate >= 0.55:
        score += 4.0
    if completed >= 2 and expectancy <= 0:
        score -= min(20.0, 5.0 + abs(expectancy) / 4.0)

    evidence_cap = 49.0
    if completed >= 10 and trading_days >= 30 and oos_positive:
        evidence_cap = 80.0
    if promotion_eligible:
        evidence_cap = 90.0
    if completed >= 50 and trading_days >= 60 and oos_positive and expectancy > 0:
        evidence_cap = 100.0
    score = round(max(0.0, min(score, evidence_cap)), 2)

    if symbol == "SPY":
        tier = "execution_benchmark"
    elif retail_lottery_risk:
        tier = "blocked"
    elif promotion_eligible and liquidity_ok:
        tier = "promotion_review"
    elif liquidity_ok:
        tier = "shadow_challenger"
    else:
        tier = "blocked"

    return {
        "symbol": symbol,
        "tier": tier,
        "rank_score": score,
        "evidence_cap": evidence_cap,
        "options_liquidity_checked": bool(liquidity),
        "options_liquidity_score": liquidity_score,
        "options_liquidity_verdict": liquidity.get("verdict"),
        "options_liquidity_ok": liquidity_ok,
        "atm_spread_pct": liquidity.get("atm_spread_pct"),
        "atm_volume_min": _integer(liquidity.get("atm_volume_min")),
        "atm_oi_min": _integer(liquidity.get("atm_oi_min")),
        "options_surface_checked": surface_ok,
        "surface_usable_for_shadow_research": surface_usable,
        "front_atm_iv": surface.get("front_atm_iv"),
        "front_implied_move_pct": surface.get("front_implied_move_pct"),
        "front_put_skew_vs_atm": surface.get("front_put_skew_vs_atm"),
        "atm_iv_term_slope_per_30d": surface.get("atm_iv_term_slope_per_30d"),
        "unsigned_unusual_contract_count": _integer(surface.get("unsigned_unusual_contract_count")),
        "institutional_flow_available": bool(surface.get("institutional_flow_available")),
        "retail_lottery_risk": retail_lottery_risk,
        "retail_lottery_risk_reasons": surface.get("retail_lottery_risk_reasons") or [],
        "hot_score": _number(hot.get("hot_score")),
        "deep_universe_score": _number(hot.get("deep_universe_score")),
        "shadow_completed_count": completed,
        "shadow_trading_day_count": trading_days,
        "out_of_sample_count": oos_count,
        "out_of_sample_expectancy_return_pct": round(expectancy, 3),
        "out_of_sample_win_rate": round(win_rate, 3),
        "out_of_sample_positive": oos_positive,
        "promotion_eligible": promotion_eligible,
        "blockers": blockers,
    }


def build_report(
    *,
    weekly_path: Path = WEEKLY_PATH,
    liquidity_path: Path = LIQUIDITY_PATH,
    shadow_path: Path = SHADOW_PATH,
    catalyst_path: Path = CATALYST_PATH,
    surface_path: Path | None = SURFACE_PATH,
    today: str | None = None,
) -> dict[str, Any]:
    weekly = _read_json(weekly_path)
    liquidity_report = _read_json(liquidity_path)
    shadow_report = _read_json(shadow_path)
    catalyst = _read_json(catalyst_path)
    surface_report = _read_json(surface_path) if surface_path is not None else {}
    hot = _by_symbol(weekly.get("hot_instruments") or [])
    liquidity = _by_symbol(liquidity_report.get("results") or [])
    shadow = _shadow_by_symbol(shadow_report)
    surface = _by_symbol(surface_report.get("results") or [])
    symbols = sorted(set(hot) | set(liquidity) | set(shadow) | set(surface) | {"SPY"})
    rankings = [
        _rank_symbol(symbol, hot.get(symbol, {}), liquidity.get(symbol, {}), shadow.get(symbol, {}), surface.get(symbol, {}))
        for symbol in symbols
    ]
    rankings.sort(key=lambda row: (row["tier"] != "execution_benchmark", -row["rank_score"], row["symbol"]))

    promotion_review = [row for row in rankings if row["tier"] == "promotion_review"]
    challengers = [row for row in rankings if row["tier"] == "shadow_challenger"]
    blocked = [row for row in rankings if row["tier"] == "blocked"]
    benchmark = next((row for row in rankings if row["symbol"] == "SPY"), None)
    today_context = catalyst.get("today") if isinstance(catalyst.get("today"), dict) else {}
    return {
        "provider": "daily_options_universe_ranker",
        "mode": "read_only_shadow_governance",
        "execution_enabled": False,
        "can_submit_orders": False,
        "non_spy_execution_allowed": False,
        "date": today or date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_benchmark": benchmark,
        "promotion_review_count": len(promotion_review),
        "shadow_challenger_count": len(challengers),
        "blocked_count": len(blocked),
        "surface_checked_count": sum(1 for row in rankings if row["options_surface_checked"]),
        "retail_lottery_risk_count": sum(1 for row in rankings if row["retail_lottery_risk"]),
        "promotion_review": promotion_review,
        "shadow_challengers": challengers,
        "blocked": blocked,
        "rankings": rankings,
        "market_catalyst_context": {
            "max_impact": today_context.get("max_impact"),
            "allowed_playbooks": today_context.get("allowed_playbooks") or [],
            "vetoes": today_context.get("vetoes") or [],
        },
        "promotion_rule": "Manual review only after at least 30 trading days, 10 completed shadow lifecycles, positive out-of-sample evidence, and a passing option-chain gate.",
        "warnings": [
            "This report cannot change the Flip Bot execution symbol or submit orders.",
            "SPY remains the execution benchmark; all non-SPY names remain shadow-only unless separately approved.",
            "Social attention contributes limited context and cannot override liquidity or out-of-sample blockers.",
            "Unsigned public-chain volume is context only; it is never labeled institutional buying or selling.",
            "Cheap high-IV wide-spread option wings can block a non-SPY shadow challenger as retail-lottery risk.",
            "Rank scores are evidence-capped so tiny samples cannot appear elite.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report()
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Daily options universe ranker wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
