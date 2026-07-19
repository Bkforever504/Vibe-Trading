"""Rank cheap, asymmetric option runners from Flip shadow P&L evidence.

Read-only. This consumes the existing Flip shadow P&L evaluator report and
identifies contracts that resemble the target profile: tiny premium paid,
large possible credit at close, tight spread, and explosive return.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
SOURCE_PATH = VIBE_HOME / "reports" / "flip-shadow-pnl-evaluator.json"
REPORT_PATH = VIBE_HOME / "reports" / "cheap-asymmetry-scanner.json"
LOG_PATH = ROOT / "data" / "cheap_asymmetry_scan_log.jsonl"

MIN_CONTRACT_COST = 10.0
MAX_CONTRACT_COST = 50.0
MIN_RETURN_PCT = 200.0
GOAL_RETURN_PCT = 500.0
MAX_SPREAD_CENTS = 20


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 1) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _labels(entry_price: float, return_pct: float, spread_cents: int | None) -> list[str]:
    labels: list[str] = []
    cost = entry_price * 100
    if MIN_CONTRACT_COST <= cost <= MAX_CONTRACT_COST:
        labels.append("cheap_contract")
    if return_pct >= GOAL_RETURN_PCT:
        labels.append("five_x_runner")
    elif return_pct >= MIN_RETURN_PCT:
        labels.append("three_x_runner")
    if spread_cents is not None and spread_cents <= 5:
        labels.append("tight_spread")
    return labels


def _reject_reasons(trade: dict[str, Any]) -> list[str]:
    entry = _safe_float(trade.get("entry_price"))
    cost = entry * 100
    ret = _safe_float(trade.get("return_pct"))
    spread_raw = trade.get("best_spread_cents")
    spread = _safe_int(spread_raw, default=-1) if spread_raw is not None else None

    reasons: list[str] = []
    if cost < MIN_CONTRACT_COST:
        reasons.append("cost_below_min")
    if cost > MAX_CONTRACT_COST:
        reasons.append("cost_above_max")
    if ret < MIN_RETURN_PCT:
        reasons.append("return_below_min")
    if spread is not None and spread > MAX_SPREAD_CENTS:
        reasons.append("spread_too_wide")
    return reasons


def score_trade(trade: dict[str, Any]) -> dict[str, Any]:
    entry = _safe_float(trade.get("entry_price"))
    best = _safe_float(trade.get("best_price"))
    ret = _safe_float(trade.get("return_pct"))
    simulated_ret = _safe_float(trade.get("simulated_exit_return_pct"), ret)
    capture_efficiency = _safe_float(trade.get("capture_efficiency"))
    spread_raw = trade.get("best_spread_cents")
    spread = _safe_int(spread_raw, default=-1) if spread_raw is not None else None
    contracts = max(1, _safe_int(trade.get("contracts"), 1))

    cost_at_open = entry * 100
    best_credit = best * 100
    best_profit = best_credit - cost_at_open
    simulated_credit = cost_at_open * (1 + simulated_ret / 100)
    asymmetry_multiple = best / entry if entry > 0 else 0.0
    labels = _labels(entry, ret, spread)
    goal_match = (
        MIN_CONTRACT_COST <= cost_at_open <= MAX_CONTRACT_COST
        and ret >= GOAL_RETURN_PCT
        and simulated_ret >= GOAL_RETURN_PCT
        and (spread is None or spread <= MAX_SPREAD_CENTS)
    )
    quality_score = (
        min(ret / 100, 8.0)
        + (2.0 if goal_match else 0.0)
        + (1.0 if spread is not None and spread <= 5 else 0.0)
        + min(capture_efficiency, 1.0)
    )

    return {
        "symbol": trade.get("symbol"),
        "right": trade.get("right"),
        "option_symbol": trade.get("option_symbol"),
        "contracts": contracts,
        "cost_at_open": round(cost_at_open, 2),
        "best_credit": round(best_credit, 2),
        "best_profit": round(best_profit, 2),
        "best_return_pct": round(ret, 2),
        "simulated_credit": round(simulated_credit, 2),
        "simulated_return_pct": round(simulated_ret, 2),
        "capture_efficiency": round(capture_efficiency, 3),
        "best_spread_cents": spread,
        "asymmetry_multiple": round(asymmetry_multiple, 2),
        "quality_score": round(quality_score, 3),
        "goal_match": goal_match,
        "labels": labels,
        "execution_mode": "shadow_only",
        "execution_enabled": False,
    }


def build_report(source_path: Path = SOURCE_PATH, day: str | None = None) -> dict[str, Any]:
    source = _load_json(source_path)
    trades = source.get("top_trades") if isinstance(source.get("top_trades"), list) else []
    candidates = []
    rejected = []
    for raw in trades:
        if not isinstance(raw, dict):
            continue
        scored = score_trade(raw)
        reasons = _reject_reasons(raw)
        if reasons:
            rejected.append({**scored, "reject_reasons": reasons})
            continue
        candidates.append(scored)

    candidates.sort(
        key=lambda item: (
            bool(item.get("goal_match")),
            float(item.get("quality_score") or 0.0),
            float(item.get("best_return_pct") or 0.0),
        ),
        reverse=True,
    )
    goal_matches = [item for item in candidates if item.get("goal_match")]
    return {
        "provider": "cheap_asymmetry_scanner",
        "mode": "read_only",
        "execution_enabled": False,
        "date": day or source.get("date") or date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(source_path),
        "thresholds": {
            "min_contract_cost": MIN_CONTRACT_COST,
            "max_contract_cost": MAX_CONTRACT_COST,
            "min_return_pct": MIN_RETURN_PCT,
            "goal_return_pct": GOAL_RETURN_PCT,
            "max_spread_cents": MAX_SPREAD_CENTS,
        },
        "summary": {
            "goal_match_count": len(goal_matches),
            "top_goal_symbols": sorted({str(item.get("symbol")) for item in goal_matches if item.get("symbol")}),
        },
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "top_candidates": candidates[:25],
        "rejected": rejected[:25],
        "promotion_note": "Read-only. Use repeated samples and signal governance before any execution wiring.",
        "warnings": [
            "No broker calls. No orders placed.",
            "Uses logged shadow estimates, not guaranteed fills.",
            "Cheap options can expire worthless; small cost does not mean high edge.",
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


def print_report(report: dict[str, Any]) -> None:
    print("\nCheap Asymmetry Scanner | read-only")
    print("=" * 72)
    print(
        f"date={report['date']} candidates={report['candidate_count']} "
        f"goal_matches={report['summary']['goal_match_count']} rejected={report['rejected_count']}"
    )
    for item in report["top_candidates"][:8]:
        print(
            f"{item['symbol']:5} {item['right']:4} {item['option_symbol']:24} "
            f"cost=${item['cost_at_open']:.2f} best=${item['best_credit']:.2f} "
            f"profit=${item['best_profit']:.2f} ret={item['best_return_pct']:.1f}% "
            f"score={item['quality_score']:.2f}"
        )
    print("No orders placed. No settings changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank cheap asymmetric option runners from shadow evidence.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--source-path", type=Path, default=SOURCE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    report = build_report(source_path=args.source_path, day=args.date)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Cheap asymmetry scanner report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
