#!/usr/bin/env python3
"""Read-only higher timeframe market map.

Builds a weekly/daily/intraday bias map for playbook selection. No broker calls,
no orders, no settings changes.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "higher-timeframe-market-map.json"
LOG_PATH = ROOT / "data" / "higher_timeframe_market_map_log.jsonl"
DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "TSLA", "AAPL", "NVDA", "PLTR", "META"]


def fetch_history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if pd.notna(parsed) else default
    except (TypeError, ValueError):
        return default


def _trend(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or len(df) < 20 or "Close" not in df:
        return {"direction": "unknown", "slope": 0.0, "close": None, "ma20": None}
    closes = df["Close"].dropna()
    if len(closes) < 20:
        return {"direction": "unknown", "slope": 0.0, "close": None, "ma20": None}
    close = _safe_float(closes.iloc[-1])
    ma20 = _safe_float(closes.tail(20).mean())
    ma20_prev = _safe_float(closes.iloc[-25:-5].mean()) if len(closes) >= 25 else _safe_float(closes.head(20).mean())
    slope = ma20 - ma20_prev
    if close > ma20 and slope > 0:
        direction = "bullish"
    elif close < ma20 and slope < 0:
        direction = "bearish"
    else:
        direction = "mixed"
    return {"direction": direction, "slope": round(slope, 4), "close": round(close, 4), "ma20": round(ma20, 4)}


def analyze_symbol(
    symbol: str,
    *,
    daily: pd.DataFrame | None = None,
    weekly: pd.DataFrame | None = None,
    intraday: pd.DataFrame | None = None,
) -> dict[str, Any]:
    daily = daily if daily is not None else fetch_history(symbol, "9mo", "1d")
    weekly = weekly if weekly is not None else fetch_history(symbol, "3y", "1wk")
    intraday = intraday if intraday is not None else fetch_history(symbol, "5d", "15m")

    daily_trend = _trend(daily)
    weekly_trend = _trend(weekly)
    intraday_trend = _trend(intraday)
    daily_dir = daily_trend["direction"]
    weekly_dir = weekly_trend["direction"]
    intraday_dir = intraday_trend["direction"]

    if daily_dir == weekly_dir and daily_dir in {"bullish", "bearish"}:
        primary = daily_dir
    else:
        primary = "mixed"

    intraday_alignment = "aligned" if primary in {"bullish", "bearish"} and intraday_dir == primary else "divergent"
    vetoes: list[str] = []
    if primary == "bullish" and intraday_alignment == "aligned":
        allowed = ["directional_long_call", "bullish_debit_spread", "selective_put_spread", "stand_aside"]
    elif primary == "bearish" and intraday_alignment == "aligned":
        allowed = ["directional_long_put", "bearish_debit_spread", "stand_aside"]
        vetoes.append("bullish_put_spread_blocked_by_htf")
    elif primary == "bearish":
        allowed = ["directional_long_put", "stand_aside", "needs_review"]
        vetoes.append("bullish_put_spread_blocked_by_htf")
    elif primary == "bullish":
        allowed = ["directional_long_call", "stand_aside", "needs_review"]
        vetoes.append("intraday_not_aligned")
    else:
        allowed = ["stand_aside", "needs_review"]
        vetoes.append("mixed_higher_timeframes")

    return {
        "symbol": symbol.upper(),
        "status": "ok" if primary != "unknown" else "no_data",
        "primary_bias": primary,
        "daily_structure": daily_trend,
        "weekly_structure": weekly_trend,
        "intraday_structure": intraday_trend,
        "intraday_alignment": intraday_alignment,
        "allowed_playbooks": allowed,
        "veto_reasons": vetoes,
    }


def build_report(symbols: list[str] | None = None) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    items = [analyze_symbol(symbol) for symbol in symbols]
    summary = dict(Counter(row.get("primary_bias", "mixed") for row in items))
    for key in ["bullish", "bearish", "mixed"]:
        summary.setdefault(key, 0)
    return {
        "provider": "higher_timeframe_market_map",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "summary": summary,
        "items": items,
        "warnings": [
            "Read-only higher timeframe context. Use as a playbook filter, not a trade trigger.",
            "No broker calls. No orders. No settings changes.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Higher timeframe market map - read-only.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.symbols)
    write_report(report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Higher timeframe market map written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
