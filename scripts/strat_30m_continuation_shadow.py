#!/usr/bin/env python3
"""Run The Strat + 30-minute continuation as a forward shadow challenger."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_ohlcv
from scripts.opening_range_breadth_scanner import fetch_intraday_bars_alpaca
from strategies.strat_30m_continuation import evaluate_strat_30m

ET = ZoneInfo("America/New_York")
SYMBOLS = ("SPY", "QQQ", "GOOGL", "AMZN", "NVDA", "AAPL", "MSFT", "META", "TSLA", "AMD")
LOG_PATH = ROOT / "data" / "strat_30m_continuation_shadow_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "strat-30m-continuation-shadow.json"


def scan(symbol: str, trading_day: date) -> tuple[dict[str, Any], pd.DataFrame | None]:
    try:
        daily = fetch_ohlcv(symbol, lookback_days=400)
        intraday = fetch_intraday_bars_alpaca(symbol, trading_day=trading_day)
        return evaluate_strat_30m(symbol, daily, intraday), intraday
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "error",
            "error": str(exc)[:240],
            "execution_enabled": False,
            "can_submit_orders": False,
        }, None


def _history() -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _episode_id(row: dict[str, Any]) -> str:
    return "|".join((row["date"], row["symbol"], str(row["shadow_direction"]), str(row["trigger_at"])))


def _outcomes(history: list[dict[str, Any]], intraday: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    resolved = {
        row.get("episode_id")
        for row in history
        if row.get("record_type") == "outcome" and int(row.get("outcome_schema_version") or 0) >= 2
    }
    now = datetime.now(ET)
    rows = []
    for signal in history:
        if signal.get("record_type") != "signal" or signal.get("episode_id") in resolved:
            continue
        trigger = datetime.fromisoformat(signal["trigger_at"])
        if now < trigger + pd.Timedelta(minutes=60):
            continue
        frame = intraday.get(signal["symbol"])
        if frame is None or frame.empty:
            continue
        future = frame[(frame.index > trigger) & (frame.index <= trigger + pd.Timedelta(minutes=60))]
        if future.empty:
            continue
        entry = float(signal["counterfactual"]["entry_underlying"])
        direction = signal["shadow_direction"]
        mfe = float(future["high"].max()) - entry if direction == "call" else entry - float(future["low"].min())
        mae = entry - float(future["low"].min()) if direction == "call" else float(future["high"].max()) - entry
        mfe = max(0.0, mfe)
        mae = max(0.0, mae)
        evaluated_at = now.isoformat()
        rows.append({
            "record_type": "outcome",
            "outcome_schema_version": 2,
            "episode_id": signal["episode_id"],
            "symbol": signal["symbol"],
            "direction": direction,
            "trigger_at": signal["trigger_at"],
            "timestamp": evaluated_at,
            "date": trigger.date().isoformat(),
            "evaluated_at": evaluated_at,
            "horizon_minutes": 60,
            "mfe_underlying_points": round(mfe, 4),
            "mae_underlying_points": round(mae, 4),
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    return rows


def run(trading_day: date | None = None) -> dict[str, Any]:
    trading_day = trading_day or datetime.now(ET).date()
    history = _history()
    existing = {row.get("episode_id") for row in history if row.get("record_type") == "signal"}
    scans = []
    intraday: dict[str, pd.DataFrame] = {}
    signals = []
    for symbol in SYMBOLS:
        row, frame = scan(symbol, trading_day)
        scans.append(row)
        if frame is not None:
            intraday[symbol] = frame
        if row.get("shadow_signal"):
            signal = {**row, "record_type": "signal"}
            signal["episode_id"] = _episode_id(signal)
            if signal["episode_id"] not in existing:
                signals.append(signal)
    outcomes = _outcomes(history, intraday)
    heartbeat = {
        "record_type": "scan",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": trading_day.isoformat(),
        "actionable_symbols": [row["symbol"] for row in scans if row.get("shadow_signal")],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _append([heartbeat, *signals, *outcomes])
    report = {
        "timestamp": heartbeat["timestamp"],
        "date": trading_day.isoformat(),
        "provider": "strat_30m_continuation_shadow",
        "execution_mode": "shadow_challenger_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "new_signals": len(signals),
        "new_outcomes": len(outcomes),
        "scans": scans,
        "promotion_requirements": {
            "minimum_forward_signals": 50,
            "minimum_trading_days": 20,
            "positive_expectancy_required": True,
            "human_review_required": True,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run(args.date)
    if args.print_report:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
