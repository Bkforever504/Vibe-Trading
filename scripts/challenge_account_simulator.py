"""Read-only small-account challenge simulator for Flip Bot trades.

This does not place orders and does not alter bot state. It replays closed
Flip Bot trade returns against a configurable starting balance and fixed risk
percentage so we can ask: "What would this system look like on a small account?"
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_TRADES_PATH = VIBE_HOME / "flip-trades.json"
REPORT_PATH = VIBE_HOME / "reports" / "challenge-account-simulator.json"
LOG_PATH = ROOT / "data" / "challenge_account_simulator_log.jsonl"
DEFAULT_RISK_PRESETS = {
    "conservative": 0.02,
    "aggressive": 0.05,
    "flip_challenge": 0.10,
    "stress_test": 0.20,
}


def load_closed_flip_trades(path: Path = DEFAULT_TRADES_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list):
        return []
    closed = [row for row in rows if isinstance(row, dict) and row.get("status") == "closed"]
    return sorted(closed, key=lambda row: (str(row.get("entry_date") or ""), str(row.get("id") or "")))


def simulate_challenge_account(
    trades: list[dict[str, Any]],
    *,
    start_balance: float = 1000.0,
    risk_pct: float = 0.02,
) -> dict[str, Any]:
    balance = float(start_balance)
    peak = balance
    equity_curve: list[dict[str, Any]] = []
    wins = 0
    losses = 0
    best_trade: dict[str, Any] | None = None
    worst_trade: dict[str, Any] | None = None
    max_drawdown_pct = 0.0

    for idx, trade in enumerate(trades, start=1):
        return_pct = _trade_return_pct(trade)
        risk_capital = balance * risk_pct
        sim_pnl = risk_capital * return_pct
        balance += sim_pnl
        peak = max(peak, balance)
        drawdown_pct = 0.0 if peak <= 0 else max(0.0, (peak - balance) / peak * 100.0)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        if sim_pnl > 0:
            wins += 1
        elif sim_pnl < 0:
            losses += 1

        row = {
            "trade_index": idx,
            "date": trade.get("exit_date") or trade.get("entry_date"),
            "symbol": trade.get("symbol"),
            "strategy": trade.get("strategy"),
            "return_pct": round(return_pct, 4),
            "risk_capital": round(risk_capital, 2),
            "sim_pnl": round(sim_pnl, 2),
            "balance": round(balance, 2),
            "drawdown_pct": round(drawdown_pct, 3),
            "source_pnl": trade.get("pnl"),
            "exit_reason": trade.get("exit_reason"),
        }
        equity_curve.append(row)
        if best_trade is None or row["sim_pnl"] > best_trade["sim_pnl"]:
            best_trade = row
        if worst_trade is None or row["sim_pnl"] < worst_trade["sim_pnl"]:
            worst_trade = row

    trade_count = len(equity_curve)
    return {
        "start_balance": round(float(start_balance), 2),
        "end_balance": round(balance, 2),
        "net_pnl": round(balance - float(start_balance), 2),
        "net_return_pct": round((balance / float(start_balance) - 1.0) * 100.0, 3) if start_balance else 0.0,
        "risk_pct": float(risk_pct),
        "trade_count": trade_count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / trade_count, 4) if trade_count else 0.0,
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "equity_curve": equity_curve,
    }


def build_report(
    trades_path: Path = DEFAULT_TRADES_PATH,
    *,
    start_balance: float = 1000.0,
    risk_pct: float = 0.02,
    risk_presets: dict[str, float] | None = None,
) -> dict[str, Any]:
    trades = load_closed_flip_trades(trades_path)
    presets = risk_presets or DEFAULT_RISK_PRESETS
    simulations = {
        name: simulate_challenge_account(trades, start_balance=start_balance, risk_pct=pct)
        for name, pct in presets.items()
    }
    primary_name = "conservative" if "conservative" in simulations else next(iter(simulations), "custom")
    primary = simulations.get(primary_name) or simulate_challenge_account(trades, start_balance=start_balance, risk_pct=risk_pct)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": "challenge_account_simulator",
        "mode": "read_only",
        "execution_enabled": False,
        "source_path": str(trades_path),
        "simulation": primary,
        "primary_simulation": primary_name,
        "simulations": simulations,
        "warnings": [
            "Read-only simulation. No broker orders are placed.",
            "Uses fixed fractional risk sizing, not the original large-account contract count.",
            "Do not use as leverage approval without a forward-tested drawdown review.",
            "Flip-challenge and stress-test presets are observational only; live bot guardrails are unchanged.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    print("\nChallenge Account Simulator | read-only")
    print("=" * 58)
    for name, sim in report.get("simulations", {"simulation": report["simulation"]}).items():
        print(
            f"{name:<15} risk={sim['risk_pct']*100:>4.1f}% "
            f"${sim['start_balance']:,.2f} -> ${sim['end_balance']:,.2f} "
            f"({sim['net_return_pct']:+.2f}%) "
            f"DD={sim['max_drawdown_pct']:.2f}% WR={sim['win_rate']*100:.1f}%"
        )
    primary = report["simulation"]
    if primary.get("best_trade"):
        print(f"Best: {primary['best_trade']['date']} {primary['best_trade']['symbol']} ${primary['best_trade']['sim_pnl']:+.2f}")
    if primary.get("worst_trade"):
        print(f"Worst: {primary['worst_trade']['date']} {primary['worst_trade']['symbol']} ${primary['worst_trade']['sim_pnl']:+.2f}")
    print(f"Report: {REPORT_PATH}\n")


def _trade_return_pct(trade: dict[str, Any]) -> float:
    try:
        pnl = float(trade.get("pnl"))
        entry = float(trade.get("entry_price"))
        contracts = int(trade.get("contracts") or 1)
        basis = entry * contracts * 100
        if basis > 0 and math.isfinite(pnl):
            return pnl / basis
    except (TypeError, ValueError):
        pass
    try:
        entry = float(trade.get("entry_price"))
        exit_price = float(trade.get("exit_price"))
        if entry > 0:
            return exit_price / entry - 1.0
    except (TypeError, ValueError):
        pass
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Flip Bot trades on a small challenge account.")
    parser.add_argument("--start", type=float, default=1000.0, help="Starting simulated balance.")
    parser.add_argument("--risk-pct", type=float, default=0.02, help="Fraction of balance risked per trade.")
    parser.add_argument(
        "--single-risk",
        action="store_true",
        help="Only run --risk-pct instead of all default risk presets.",
    )
    parser.add_argument("--trades-path", type=Path, default=DEFAULT_TRADES_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    presets = {"custom": args.risk_pct} if args.single_risk else None
    report = build_report(args.trades_path, start_balance=args.start, risk_pct=args.risk_pct, risk_presets=presets)
    write_report(report, args.report_path)
    if args.do_print:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
