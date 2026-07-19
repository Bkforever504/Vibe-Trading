#!/usr/bin/env python3
"""Read-only post-hardening equity curve and maximum-drawdown report."""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

VIBE_HOME = Path.home() / ".vibe-trading"
TRADES_PATH = VIBE_HOME / "flip-trades.json"
REPORT_PATH = VIBE_HOME / "reports" / "flip-equity-curve.json"
ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "flip_equity_curve_log.jsonl"

HARDENING_START = date(2026, 6, 29)

_COMPLETENESS_FIELDS = (
    "pnl", "entry_price", "exit_price", "entry_date",
    "exit_date", "exit_reason", "contracts", "strategy",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _read_trades(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in payload if isinstance(r, dict)] if isinstance(payload, list) else []


def _dedupe_key(trade: dict[str, Any]) -> str:
    order_id = str(trade.get("alpaca_order_id") or "").strip()
    return order_id if order_id else str(trade.get("id") or "").strip()


def _completeness(trade: dict[str, Any], index: int) -> tuple[int, int, int]:
    populated = sum(trade.get(f) not in (None, "") for f in _COMPLETENESS_FIELDS)
    original_bonus = 0 if str(trade.get("id") or "").startswith("recovered-") else 1
    return populated, original_bonus, -index


def dedupe_flip_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate closed trades by alpaca_order_id. Never mutates state."""
    selected: dict[str, tuple[int, dict[str, Any]]] = {}
    passthrough: list[tuple[int, dict[str, Any]]] = []
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            continue
        key = _dedupe_key(trade)
        if trade.get("status") != "closed" or not key:
            passthrough.append((index, trade))
            continue
        current = selected.get(key)
        if current is None or _completeness(trade, index) > _completeness(current[1], current[0]):
            selected[key] = (index, trade)
    rows = passthrough + list(selected.values())
    rows.sort(key=lambda item: item[0])
    return [t for _, t in rows]


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _exit_sort_key(trade: dict[str, Any], source_index: int) -> tuple[str, int, str, int]:
    exit_at = _timestamp(trade.get("exit_at"))
    day = str(trade.get("exit_date") or trade.get("entry_date") or "")
    if exit_at is not None:
        return day, 0, exit_at.astimezone(timezone.utc).isoformat(), source_index
    return day, 1, "", source_index


def build_report(trades_path: Path = TRADES_PATH) -> dict[str, Any]:
    all_trades = _read_trades(trades_path)
    closed = dedupe_flip_trades([t for t in all_trades if t.get("status") == "closed"])

    pre_hardening: list[dict[str, Any]] = []
    post_hardening: list[dict[str, Any]] = []
    skipped_no_pnl: list[str] = []

    for t in closed:
        try:
            entry_date = date.fromisoformat(str(t.get("entry_date") or ""))
        except (ValueError, TypeError):
            skipped_no_pnl.append(t.get("id", "unknown"))
            continue
        if _number(t.get("pnl")) is None:
            skipped_no_pnl.append(t.get("id", "unknown"))
            continue
        if entry_date < HARDENING_START:
            pre_hardening.append(t)
        else:
            post_hardening.append(t)

    source_order = {id(trade): index for index, trade in enumerate(closed)}
    post_hardening.sort(key=lambda trade: _exit_sort_key(trade, source_order[id(trade)]))

    cumulative = 0.0
    peak = 0.0
    peak_trade_num = 0
    max_dd_dollars = 0.0
    max_dd_peak_trade_num = 0
    max_dd_trough_trade_num = 0
    wins = 0
    breakevens = 0
    gross_profit = 0.0
    gross_loss = 0.0
    curve: list[dict[str, Any]] = []

    for i, t in enumerate(post_hardening, start=1):
        pnl = float(t.get("pnl") or 0)
        cumulative = round(cumulative + pnl, 2)

        if cumulative > peak:
            peak = cumulative
            peak_trade_num = i

        dd_dollars = round(cumulative - peak, 2)
        if dd_dollars < max_dd_dollars:
            max_dd_dollars = dd_dollars
            max_dd_peak_trade_num = peak_trade_num
            max_dd_trough_trade_num = i

        if pnl > 0:
            wins += 1
            gross_profit = round(gross_profit + pnl, 2)
        elif pnl < 0:
            gross_loss = round(gross_loss + abs(pnl), 2)
        else:
            breakevens += 1

        curve.append({
            "trade_num": i,
            "trade_id": t.get("id"),
            "alpaca_order_id": t.get("alpaca_order_id"),
            "date": str(t.get("exit_date") or t.get("entry_date") or ""),
            "exit_at": t.get("exit_at"),
            "strategy": t.get("strategy"),
            "symbol": t.get("symbol"),
            "right": t.get("right"),
            "contracts": t.get("contracts"),
            "pnl": pnl,
            "cumulative_pnl": cumulative,
            "exit_reason": t.get("exit_reason"),
            "drawdown_dollars": dd_dollars,
        })

    n = len(post_hardening)
    current_dd_dollars = round(cumulative - peak, 2) if n else 0.0
    net_pnl = round(cumulative, 2)
    win_rate = round(wins / n, 4) if n else None
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
    expectancy = round(net_pnl / n, 2) if n else None

    has_drawdown = max_dd_dollars < 0
    max_dd_pct = round(max_dd_dollars / peak * 100, 2) if has_drawdown and peak > 0 else (None if has_drawdown else 0.0)
    current_dd_pct = round(current_dd_dollars / peak * 100, 2) if current_dd_dollars < 0 and peak > 0 else (None if current_dd_dollars < 0 else 0.0)

    max_dd_peak_date = curve[max_dd_peak_trade_num - 1]["date"] if has_drawdown and max_dd_peak_trade_num > 0 else None
    max_dd_trough_date = curve[max_dd_trough_trade_num - 1]["date"] if has_drawdown and max_dd_trough_trade_num > 0 else None

    summary: dict[str, Any] = {
        "hardening_start_date": str(HARDENING_START),
        "post_hardening_trades": n,
        "pre_hardening_excluded": len(pre_hardening),
        "skipped_no_pnl_count": len(skipped_no_pnl),
        "net_pnl": net_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "wins": wins,
        "losses": n - wins - breakevens,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy_per_trade": expectancy,
        "peak_cumulative_pnl": round(peak, 2),
        "max_drawdown_dollars": round(max_dd_dollars, 2),
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_peak_trade_num": max_dd_peak_trade_num if has_drawdown else None,
        "max_drawdown_trough_trade_num": max_dd_trough_trade_num if has_drawdown else None,
        "max_drawdown_peak_date": max_dd_peak_date,
        "max_drawdown_trough_date": max_dd_trough_date,
        "current_drawdown_dollars": round(current_dd_dollars, 2),
        "current_drawdown_pct": current_dd_pct,
        "curve_basis": "zero_start_realized_pnl",
        "drawdown_pct_basis": "peak_cumulative_realized_profit",
        "account_equity_drawdown_available": False,
    }

    return {
        "provider": "flip_equity_curve_report",
        "mode": "read_only_realized_pnl_analytics",
        "generated_at": _utc_now(),
        "source_path": str(trades_path),
        "execution_enabled": False,
        "can_submit_orders": False,
        "summary": summary,
        "equity_curve": curve,
        "warnings": [
            "Drawdown percentage is relative to peak cumulative post-hardening profit, not total account equity.",
            "Trades without exit_at use durable file order within the exit date; their intraday chronology is not inferred.",
            "This report cannot submit orders, change thresholds, or act as an execution gate.",
        ],
    }


def save_report(
    path: Path = REPORT_PATH,
    trades_path: Path = TRADES_PATH,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    report = build_report(trades_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Flip equity curve and max drawdown report (read-only)")
    parser.add_argument("--trades-path", type=Path, default=TRADES_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", help="Print summary to stdout")
    args = parser.parse_args()

    report = save_report(args.report_path, args.trades_path, args.log_path)
    if args.print:
        s = report["summary"]
        print(f"Flip Equity Curve  [{report['generated_at']}]")
        print(f"Post-hardening trades : {s['post_hardening_trades']}")
        print(f"Pre-hardening excluded: {s['pre_hardening_excluded']}")
        print(f"Net P&L               : ${s['net_pnl']:,.2f}")
        if s["win_rate"] is not None:
            print(f"Win rate              : {s['win_rate']:.1%}")
        if s["profit_factor"] is not None:
            print(f"Profit factor         : {s['profit_factor']:.2f}")
        if s["expectancy_per_trade"] is not None:
            print(f"Expectancy            : ${s['expectancy_per_trade']:,.2f}/trade")
        print(f"Peak cumulative P&L   : ${s['peak_cumulative_pnl']:,.2f}")
        max_dd_text = f"{s['max_drawdown_pct']:.1f}%" if s["max_drawdown_pct"] is not None else "n/a"
        print(f"Max drawdown          : ${s['max_drawdown_dollars']:,.2f}  ({max_dd_text})")
        if s["max_drawdown_peak_date"]:
            print(
                f"  peak trade {s['max_drawdown_peak_trade_num']} ({s['max_drawdown_peak_date']}) "
                f"-> trough trade {s['max_drawdown_trough_trade_num']} ({s['max_drawdown_trough_date']})"
            )
        current_dd_text = f"{s['current_drawdown_pct']:.1f}%" if s["current_drawdown_pct"] is not None else "n/a"
        print(f"Current drawdown      : ${s['current_drawdown_dollars']:,.2f}  ({current_dd_text})")
        print("Drawdown % basis      : peak cumulative realized profit (not account equity)")
        print(f"Report saved          : {args.report_path}")


if __name__ == "__main__":
    main()
