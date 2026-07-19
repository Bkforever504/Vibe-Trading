"""Read-only feasibility report for operating with a $1,000 account."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_TRADES = VIBE_HOME / "flip-trades.json"
DEFAULT_PUBLIC_LAB = VIBE_HOME / "reports" / "public-bot-replication-lab.json"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "micro-account-readiness.json"
POST_HARDENING_START = "2026-06-29"


def _load(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def one_contract_replay(trades: list[dict[str, Any]], start_balance: float) -> dict[str, Any]:
    balance = float(start_balance)
    peak = balance
    max_drawdown = 0.0
    rows = []
    for trade in trades:
        contracts = max(1, int(trade.get("contracts") or 1))
        pnl = _finite(trade.get("pnl"))
        entry = _finite(trade.get("entry_price"))
        if pnl is None or entry is None or entry <= 0:
            continue
        scaled_pnl = pnl / contracts
        balance += scaled_pnl
        peak = max(peak, balance)
        drawdown = 0.0 if peak <= 0 else (peak - balance) / peak
        max_drawdown = max(max_drawdown, drawdown)
        rows.append({
            "date": trade.get("entry_date"),
            "strategy": trade.get("strategy"),
            "entry_premium_one_contract": round(entry * 100.0, 2),
            "pnl_one_contract": round(scaled_pnl, 2),
            "balance": round(balance, 2),
            "drawdown_pct": round(drawdown * 100.0, 3),
        })
    return {
        "start_balance": round(float(start_balance), 2),
        "end_balance": round(balance, 2),
        "net_pnl": round(balance - float(start_balance), 2),
        "trade_count": len(rows),
        "wins": sum(float(row["pnl_one_contract"]) > 0 for row in rows),
        "losses": sum(float(row["pnl_one_contract"]) < 0 for row in rows),
        "max_drawdown_pct": round(max_drawdown * 100.0, 3),
        "rows": rows,
        "warning": "This scales historical fills to one contract and is not executable fixed-fractional sizing or untouched evidence.",
    }


def build_report(
    trades_payload: Any,
    public_lab: dict[str, Any],
    *,
    account_size: float = 1000.0,
    max_risk_pct: float = 0.02,
) -> dict[str, Any]:
    rows = trades_payload if isinstance(trades_payload, list) else []
    post = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("status") == "closed"
        and str(row.get("entry_date") or "")[:10] >= POST_HARDENING_START
    ]
    premiums = [float(row["entry_price"]) * 100.0 for row in post if _finite(row.get("entry_price")) is not None]
    risk_budget = float(account_size) * float(max_risk_pct)
    planned_stop_risks = [premium * 0.30 for premium in premiums]
    momentum = next(
        (row for row in public_lab.get("strategies", []) if row.get("strategy") == "micro_account_50pct_dual_momentum_50pct_cash"),
        None,
    )
    option_fit_count = sum(premium <= risk_budget for premium in premiums)
    planned_stop_fit_count = sum(risk <= risk_budget for risk in planned_stop_risks)
    replay = one_contract_replay(post, account_size)
    options_ready = bool(len(post) >= 100 and option_fit_count == len(post) and replay["max_drawdown_pct"] <= 8.0)
    momentum_forward = (momentum or {}).get("forward_2025_plus") or {}
    momentum_development = (momentum or {}).get("development_through_2024") or {}
    momentum_stress = (momentum or {}).get("double_cost_forward_2025_plus") or {}
    return {
        "provider": "micro_account_readiness_report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "account_size": round(float(account_size), 2),
        "risk_policy": {
            "max_risk_pct_per_trade": float(max_risk_pct),
            "max_risk_dollars": round(risk_budget, 2),
            "target_max_drawdown_pct": 8.0,
            "daily_income_target_allowed": False,
        },
        "flip_options_lane": {
            "status": "paper_observation_only" if not options_ready else "eligible_for_manual_review",
            "post_hardening_trade_count": len(post),
            "historical_one_contract_premium_min": round(min(premiums), 2) if premiums else None,
            "historical_one_contract_premium_max": round(max(premiums), 2) if premiums else None,
            "full_premium_fit_count_at_risk_budget": option_fit_count,
            "planned_30pct_stop_fit_count_at_risk_budget": planned_stop_fit_count,
            "one_contract_replay": replay,
            "reason": "Whole option contracts do not support reliable 2% risk sizing at the observed SPY premiums.",
        },
        "fractional_momentum_lane": {
            "status": "isolated_virtual_paper_active",
            "deployment_fraction": 0.50,
            "cash_reserve_fraction": 0.50,
            "forward_2025_plus": momentum_forward,
            "development_through_2024": momentum_development,
            "double_cost_forward_2025_plus": momentum_stress,
            "strategy_confidence_score_out_of_10": 6.5,
            "operational_fit_score_out_of_10": 9.0,
            "execution": "A separate $1,000 virtual paper ledger now models point-in-time fractional fills; broker and live orders remain disabled.",
        },
        "readiness": {
            "live_ready": False,
            "profitability_guaranteed": False,
            "next_gate": "Run the $1,000 shadow ledger for at least 26 weekly decisions and compare broker-executable fractional fills with the model.",
        },
        "warnings": [
            "A $1,000 account cannot produce dependable living income without taking ruinous risk.",
            "Green days are not a valid optimization target; positive expectancy and bounded drawdown are.",
            "Historical one-contract scaling ignores whether a 2% risk budget could actually purchase the contract.",
            "The 8% virtual-ledger liquidation halt is a new risk overlay and was not part of the 21.25% historical result.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--public-lab", type=Path, default=DEFAULT_PUBLIC_LAB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--account-size", type=float, default=1000.0)
    parser.add_argument("--risk-pct", type=float, default=0.02)
    args = parser.parse_args()
    report = build_report(_load(args.trades, []), _load(args.public_lab, {}), account_size=args.account_size, max_risk_pct=args.risk_pct)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lane = report["flip_options_lane"]
    print(f"$1,000 risk budget: ${report['risk_policy']['max_risk_dollars']:.2f}")
    print(f"Observed option premium range: ${lane['historical_one_contract_premium_min']:.2f}-${lane['historical_one_contract_premium_max']:.2f}")
    print(f"Options lane: {lane['status']}")
    print(f"Momentum lane: {report['fractional_momentum_lane']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
