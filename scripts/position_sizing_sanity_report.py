#!/usr/bin/env python3
"""Read-only position sizing and tail-risk sanity report.

This report checks whether Flip Bot sizing is consistent with configured risk
limits and whether recent realized returns look survivable under simple
tail-bound stress assumptions. It does not place orders or change settings.
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
DEFAULT_TRADES_PATH = VIBE_HOME / "flip-trades.json"
LOG_PATH = ROOT / "data" / "position_sizing_sanity_log.jsonl"

MAX_RISK_PCT = 0.02
MAX_CONTRACTS = 5
POST_CONFIG_START_DATE = "2026-06-29"
TAIL_LOSS_THRESHOLD = 0.50


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _load_closed_trades(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("status") == "closed"]


def trade_return_pct(trade: dict[str, Any]) -> float:
    pnl = _safe_float(trade.get("pnl"))
    entry = _safe_float(trade.get("entry_price"))
    contracts = int(trade.get("contracts") or 1)
    basis = (entry or 0.0) * max(contracts, 1) * 100
    if pnl is not None and basis > 0:
        return pnl / basis
    exit_price = _safe_float(trade.get("exit_price"))
    if entry and exit_price is not None:
        return exit_price / entry - 1.0
    return 0.0


def evaluate_candidate_sizing(
    *,
    account_size: float,
    option_price: float,
    max_risk_pct: float = MAX_RISK_PCT,
    max_contracts: int = MAX_CONTRACTS,
) -> dict[str, Any]:
    risk_budget = max(0.0, float(account_size) * float(max_risk_pct))
    contract_notional = max(0.0, float(option_price) * 100.0)
    raw_contracts = int(risk_budget // contract_notional) if contract_notional > 0 else 0
    recommended = min(raw_contracts, int(max_contracts))
    estimated_notional = round(recommended * contract_notional, 2)
    return {
        "account_size": round(float(account_size), 2),
        "option_price": round(float(option_price), 4),
        "max_risk_pct": float(max_risk_pct),
        "risk_budget": round(risk_budget, 2),
        "contract_notional": round(contract_notional, 2),
        "raw_contracts": raw_contracts,
        "recommended_contracts": recommended,
        "max_contracts": int(max_contracts),
        "estimated_notional": estimated_notional,
        "contract_cap_binding": raw_contracts > int(max_contracts),
        "risk_pct_binding": raw_contracts <= int(max_contracts) and raw_contracts > 0,
        "verdict": "blocked_unaffordable" if recommended < 1 else "sizing_within_config",
    }


def tail_bounds(returns: list[float], *, tail_loss_threshold: float = TAIL_LOSS_THRESHOLD) -> dict[str, Any]:
    losses = [max(0.0, -float(value)) for value in returns]
    n = len(losses)
    if n == 0 or tail_loss_threshold <= 0:
        return {
            "sample_count": n,
            "tail_loss_threshold": tail_loss_threshold,
            "empirical_tail_rate": 0.0,
            "markov_upper_bound": 0.0,
            "chebyshev_upper_bound": 0.0,
            "chernoff_style_upper_bound": 0.0,
        }
    mean_loss = sum(losses) / n
    variance = sum((loss - mean_loss) ** 2 for loss in losses) / n
    empirical = sum(1 for loss in losses if loss >= tail_loss_threshold) / n
    markov = min(1.0, mean_loss / tail_loss_threshold)
    chebyshev = min(markov, variance / (variance + max(tail_loss_threshold - mean_loss, 0.0) ** 2)) if variance > 0 else 0.0
    chernoff_style = min(chebyshev, math.exp(-2.0 * n * max(tail_loss_threshold - mean_loss, 0.0) ** 2))
    return {
        "sample_count": n,
        "tail_loss_threshold": float(tail_loss_threshold),
        "mean_loss": round(mean_loss, 4),
        "loss_variance": round(variance, 6),
        "empirical_tail_rate": round(empirical, 4),
        "markov_upper_bound": round(markov, 4),
        "chebyshev_upper_bound": round(chebyshev, 4),
        "chernoff_style_upper_bound": round(chernoff_style, 4),
        "note": "Bounds are conservative sanity checks, not price forecasts.",
    }


def _summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_safe_float(trade.get("pnl")) for trade in trades]
    pnls = [pnl for pnl in pnls if pnl is not None]
    returns = [trade_return_pct(trade) for trade in trades]
    max_contracts_seen = max((int(trade.get("contracts") or 0) for trade in trades), default=0)
    return {
        "trade_count": len(trades),
        "total_pnl": round(sum(pnls), 2) if pnls else 0.0,
        "win_rate": round(sum(1 for pnl in pnls if pnl > 0) / len(pnls), 4) if pnls else 0.0,
        "max_contracts_seen": max_contracts_seen,
        "returns": [round(value, 4) for value in returns],
        "tail_bounds": tail_bounds(returns),
    }


def build_report(
    trades_path: Path = DEFAULT_TRADES_PATH,
    *,
    account_size: float = 5000.0,
    option_price: float = 1.0,
    day: str | None = None,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    trades = _load_closed_trades(trades_path)
    post_config_trades = [
        trade for trade in trades
        if str(trade.get("entry_date") or trade.get("exit_date") or "") >= POST_CONFIG_START_DATE
    ]
    all_time = _summarize_trades(trades)
    post_config = _summarize_trades(post_config_trades)
    sizing = evaluate_candidate_sizing(account_size=account_size, option_price=option_price)
    warnings = [
        "Read-only sizing review. No orders placed and no settings changed.",
        "Tail bounds are risk sanity checks, not forecasts.",
    ]
    if all_time["max_contracts_seen"] > MAX_CONTRACTS:
        warnings.append("pre_fix_contract_artifact_detected")
    if sizing["recommended_contracts"] < 1:
        verdict = "blocked_unaffordable_observe_only"
    elif all_time["max_contracts_seen"] > MAX_CONTRACTS and post_config["max_contracts_seen"] <= MAX_CONTRACTS:
        verdict = "risk_controls_pass_observe_only"
    elif post_config["max_contracts_seen"] > MAX_CONTRACTS:
        verdict = "risk_controls_need_review"
    else:
        verdict = "risk_controls_pass_observe_only"
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "position_sizing_sanity_report",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source_path": str(trades_path),
        "configured_limits": {
            "max_risk_pct": MAX_RISK_PCT,
            "max_contracts": MAX_CONTRACTS,
            "post_config_start_date": POST_CONFIG_START_DATE,
            "tail_loss_threshold": TAIL_LOSS_THRESHOLD,
        },
        "candidate_sizing": sizing,
        "all_time": all_time,
        "post_config": post_config,
        "verdict": verdict,
        "warnings": warnings,
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> Path:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")
    return log_path


def print_report(report: dict[str, Any]) -> None:
    print("\nPosition Sizing Sanity Report | read-only")
    print("=" * 84)
    sizing = report["candidate_sizing"]
    print(
        f"verdict={report['verdict']} account=${sizing['account_size']:,.2f} "
        f"option=${sizing['option_price']:.2f} contracts={sizing['recommended_contracts']} "
        f"risk_budget=${sizing['risk_budget']:,.2f}"
    )
    print(
        f"all_time trades={report['all_time']['trade_count']} pnl=${report['all_time']['total_pnl']:,.2f} "
        f"max_contracts={report['all_time']['max_contracts_seen']}"
    )
    print(
        f"post_config trades={report['post_config']['trade_count']} pnl=${report['post_config']['total_pnl']:,.2f} "
        f"win_rate={report['post_config']['win_rate'] * 100:.1f}% "
        f"max_contracts={report['post_config']['max_contracts_seen']}"
    )
    tb = report["post_config"]["tail_bounds"]
    print(
        f"tail risk threshold={tb['tail_loss_threshold']:.0%} "
        f"empirical={tb['empirical_tail_rate']:.1%} "
        f"markov<={tb['markov_upper_bound']:.1%} "
        f"chebyshev<={tb['chebyshev_upper_bound']:.1%} "
        f"chernoff_style<={tb['chernoff_style_upper_bound']:.1%}"
    )
    print("No orders placed. No settings changed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades-path", type=Path, default=DEFAULT_TRADES_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--account-size", type=float, default=5000.0)
    parser.add_argument("--option-price", type=float, default=1.0)
    parser.add_argument("--print", action="store_true", dest="print_output")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    report = build_report(args.trades_path, account_size=args.account_size, option_price=args.option_price)
    if args.print_output:
        print_report(report)
    if not args.no_write:
        append_log(report, args.log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
