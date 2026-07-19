#!/usr/bin/env python3
"""Log deterministic MNQ/MES ICT macro candidates without trading."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_catalyst_calendar import risk_window_for_date
from strategies.ict_macro_shadow import build_session_levels, evaluate_macro_setup

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "ict-macro-shadow.json"
LOG_PATH = ROOT / "data" / "ict_macro_shadow_log.jsonl"
SYMBOLS = {"MNQ": "NQ=F", "MES": "ES=F"}


def fetch_futures(symbol: str, period: str = "10d") -> pd.DataFrame:
    import yfinance as yf

    frame = yf.Ticker(SYMBOLS[symbol]).history(period=period, interval="5m", prepost=True, auto_adjust=False)
    if frame.empty:
        raise ValueError(f"No 5-minute futures data for {symbol}")
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame


def scan_symbol(symbol: str, bars: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        bars = bars if bars is not None else fetch_futures(symbol)
        trading_day = pd.to_datetime(bars.index).max().date()
        levels = build_session_levels(bars, trading_day)
        day = bars[pd.to_datetime(bars.index).date == trading_day]
        risk = risk_window_for_date(trading_day)
        full_day_veto = risk.get("max_impact") == "high" and any(
            event.get("time_et") in {"all_day", "14:00"} for event in risk.get("events", [])
        )
        result = evaluate_macro_setup(day, levels=levels, high_impact_news_veto=full_day_veto)
        return {
            "symbol": symbol,
            "data_symbol": SYMBOLS[symbol],
            "trading_day": trading_day.isoformat(),
            "levels": levels,
            "macro_risk": risk,
            **result,
        }
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "error",
            "error": str(exc)[:200],
            "mode": "shadow_only",
            "execution_enabled": False,
            "can_submit_orders": False,
        }


def build_report(symbols: list[str] | None = None) -> dict[str, Any]:
    symbols = symbols or list(SYMBOLS)
    rows = [scan_symbol(symbol) for symbol in symbols]
    return {
        "schema_version": 1,
        "provider": "ict_macro_shadow_logger",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "rows": rows,
        "signal_count": sum(bool(row.get("shadow_signal")) for row in rows),
        "warnings": [
            "Social ICT terminology has been converted into deterministic OHLC rules.",
            "No profitability claim is accepted without chronological replay and forward outcomes.",
            "This logger cannot place, modify, or cancel orders.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True, default=str) + "\n")


def print_report(report: dict[str, Any]) -> None:
    print("\nICT Macro Shadow | no orders")
    print("=" * 76)
    for row in report["rows"]:
        print(
            f"{row['symbol']:<4} {row.get('status'):<28} "
            f"direction={row.get('direction', '-')} entry={row.get('entry', '-')}"
        )
    print(f"signals={report['signal_count']} execution_enabled={report['execution_enabled']}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="MNQ,MES")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    parser.add_argument("--no-append", action="store_true")
    args = parser.parse_args()
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    report = build_report(symbols)
    write_report(report, args.report_path)
    if not args.no_append:
        append_log(report, args.log_path)
    if args.do_print:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
