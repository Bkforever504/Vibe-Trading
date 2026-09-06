#!/usr/bin/env python3
"""Exact daily RSI(2) / 200-SMA pullback challenger from the supplied rules.

Rules are deliberately narrow: long only; enter on the daily close when
RSI(2) < 10 and close > 200-day SMA; exit on a daily close when RSI(2) > 70
or after ten subsequent sessions, whichever comes first.  This script reports
underlying percentage returns only.  It does not model futures rolls, margin,
options, fills, or execution.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "daily_rsi2_200sma_hold_tournament.json"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "daily-rsi2-200sma-hold-tournament.json"
IN_SAMPLE_END = "2024-12-31"
OUT_OF_SAMPLE_START = "2025-01-01"
INSTRUMENTS = {"ES": "ES=F", "NQ": "NQ=F"}


def _rsi2(close: pd.Series) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).rolling(2).mean()
    loss = (-change.clip(upper=0)).rolling(2).mean()
    relative = gain / loss.replace(0.0, math.nan)
    return (100.0 - 100.0 / (1.0 + relative)).fillna(100.0)


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.copy()
    bars.columns = [str(column).lower() for column in bars.columns]
    if "close" not in bars:
        raise ValueError("daily bars require a close column")
    if not isinstance(bars.index, pd.DatetimeIndex):
        bars.index = pd.to_datetime(bars.index, utc=True)
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    bars = bars.sort_index()
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars = bars.dropna(subset=["close"])
    bars["rsi2"] = _rsi2(bars["close"])
    bars["sma200"] = bars["close"].rolling(200).mean()
    return bars


def simulate(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Use only each completed close; no intrabar exits or forward entry data."""
    bars = prepare(frame)
    trades: list[dict[str, Any]] = []
    open_trade: dict[str, Any] | None = None
    for timestamp, row in bars.iterrows():
        close = float(row["close"])
        if open_trade is None:
            if pd.notna(row["sma200"]) and float(row["rsi2"]) < 10.0 and close > float(row["sma200"]):
                open_trade = {
                    "entry_at": timestamp.isoformat(), "entry_close": close,
                    "entry_rsi2": round(float(row["rsi2"]), 4), "sessions_held": 0,
                }
            continue
        open_trade["sessions_held"] += 1
        exit_rsi = float(row["rsi2"]) > 70.0
        exit_timeout = int(open_trade["sessions_held"]) >= 10
        if not (exit_rsi or exit_timeout):
            continue
        entry = float(open_trade["entry_close"])
        trades.append({
            **open_trade,
            "exit_at": timestamp.isoformat(), "exit_close": close,
            "exit_rsi2": round(float(row["rsi2"]), 4),
            "exit_reason": "rsi2_above_70" if exit_rsi else "ten_session_timeout",
            "underlying_return_pct": round((close / entry - 1.0) * 100.0, 6),
        })
        open_trade = None
    return trades


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["underlying_return_pct"]) for row in trades]
    gains = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    return {
        "trades": len(values),
        "win_rate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
        "average_return_pct": round(sum(values) / len(values), 6) if values else None,
        "median_return_pct": round(float(pd.Series(values).median()), 6) if values else None,
        "profit_factor": round(sum(gains) / sum(losses), 6) if losses else None,
        "total_return_pct_uncompounded": round(sum(values), 6),
    }


def split_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    in_sample = [row for row in trades if str(row["entry_at"])[:10] <= IN_SAMPLE_END]
    out_sample = [row for row in trades if str(row["entry_at"])[:10] >= OUT_OF_SAMPLE_START]
    return {"all": metrics(trades), "in_sample_2008_2024": metrics(in_sample), "out_of_sample_2025_plus": metrics(out_sample)}


def _fetch(symbol: str, start: str) -> pd.DataFrame:
    import yfinance as yf

    frame = yf.Ticker(symbol).history(start=start, interval="1d", auto_adjust=False)
    if frame.empty:
        raise RuntimeError(f"no daily data returned for {symbol}")
    return frame


def run(frames: dict[str, pd.DataFrame] | None = None, start: str = "2008-01-01") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name, ticker in INSTRUMENTS.items():
        try:
            frame = frames[name] if frames is not None else _fetch(ticker, start)
            trades = simulate(frame)
            rows.append({
                "instrument": name, "ticker": ticker, "status": "evaluated",
                "first_bar": str(prepare(frame).index.min()), "last_bar": str(prepare(frame).index.max()),
                "trade_metrics": split_report(trades), "trades": trades,
            })
        except Exception as exc:
            rows.append({"instrument": name, "ticker": ticker, "status": "data_unavailable", "error": f"{type(exc).__name__}: {exc}"[:180]})
    oos = [row["trade_metrics"]["out_of_sample_2025_plus"] for row in rows if row.get("status") == "evaluated"]
    return {
        "schema_version": 1,
        "experiment": "DAILY-RSI2-200SMA-HOLD-2026-08-31",
        "mode": "historical_underlying_research_only",
        "execution_enabled": False,
        "rank_effect": "none",
        "rules": {
            "entry": "daily close: RSI(2) < 10 and close > 200-day SMA",
            "exit": "daily close: RSI(2) > 70 or after 10 subsequent sessions, whichever occurs first",
            "side": "long only", "stop": "none", "sizing": "not modeled",
        },
        "split": {"in_sample_end": IN_SAMPLE_END, "out_of_sample_start": OUT_OF_SAMPLE_START},
        "results": rows,
        "out_of_sample_summary": {
            "evaluated_instruments": len(oos),
            "all_instruments_positive_average_return": bool(oos) and all((row.get("average_return_pct") or 0.0) > 0 for row in oos),
            "minimum_oos_trades": min((int(row.get("trades") or 0) for row in oos), default=0),
        },
        "promotion_status": "blocked_pending_point_in_time_futures_roll_and_cost_model_plus_forward_shadow",
        "warnings": [
            "Underlying percent returns are not futures-contract or options returns.",
            "No stop is reproduced because it is in the stated rule; that does not make the rule suitable for capital.",
            "No scanner ranking, alert, sizing, or order authority is granted by this experiment.",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2008-01-01")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run(start=args.start)
    for path in (args.output, args.report):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps({"out_of_sample_summary": report["out_of_sample_summary"], "results": report["results"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
