#!/usr/bin/env python3
"""Run the shadow-only Condition-Zone-Trigger research scanner."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.czt_order_flow import evaluate_czt

ET = ZoneInfo("America/New_York")
SYMBOLS = ("SPY", "QQQ", "IWM")
LOG_PATH = ROOT / "data" / "czt_order_flow_shadow_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "czt-order-flow-shadow.json"


def _regular_session(timestamp: Any) -> bool:
    parsed = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else _parse_time(str(timestamp))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ET)
    local = parsed.astimezone(ET)
    return dtime(9, 30) <= local.time() < dtime(16, 0)


def _fetch_alpaca(symbol: str) -> tuple[list[dict[str, Any]], str]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from scripts import market_data

    market_data._load_env()  # noqa: SLF001 - shared operational credential loader
    if not market_data._ALPACA_KEY or not market_data._ALPACA_SECRET:  # noqa: SLF001
        raise RuntimeError("Alpaca credentials unavailable")
    client = StockHistoricalDataClient(
        api_key=market_data._ALPACA_KEY,  # noqa: SLF001
        secret_key=market_data._ALPACA_SECRET,  # noqa: SLF001
    )
    now = datetime.now(ET)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=now.replace(hour=9, minute=30, second=0, microsecond=0),
        end=now,
        adjustment="all",
        feed="iex",
    )
    frame = client.get_stock_bars(request).df
    if frame.empty:
        raise RuntimeError(f"No Alpaca intraday bars for {symbol}")
    if getattr(frame.index, "nlevels", 1) > 1:
        frame = frame.xs(symbol, level="symbol")
    rows = []
    for timestamp, row in frame.iterrows():
        if not _regular_session(timestamp):
            continue
        rows.append({
            "timestamp": timestamp.isoformat(),
            "open": row["open"], "high": row["high"], "low": row["low"],
            "close": row["close"], "volume": row["volume"],
        })
    return rows, "alpaca_iex_minute_bars"


def _fetch_yfinance(symbol: str) -> tuple[list[dict[str, Any]], str]:
    import yfinance as yf

    frame = yf.Ticker(symbol).history(period="1d", interval="1m", auto_adjust=True)
    if frame.empty:
        raise RuntimeError(f"No yfinance intraday bars for {symbol}")
    rows = []
    for timestamp, row in frame.iterrows():
        if not _regular_session(timestamp):
            continue
        rows.append({
            "timestamp": timestamp.isoformat(),
            "open": row["Open"], "high": row["High"], "low": row["Low"],
            "close": row["Close"], "volume": row["Volume"],
        })
    return rows, "yfinance_minute_bars_fallback"


def fetch_bars(symbol: str) -> tuple[list[dict[str, Any]], str]:
    try:
        return _fetch_alpaca(symbol)
    except Exception as alpaca_error:
        rows, source = _fetch_yfinance(symbol)
        return rows, f"{source}; alpaca_error={str(alpaca_error)[:100]}"


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _append(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _episode_id(snapshot: dict[str, Any]) -> str:
    return "|".join((snapshot["symbol"], snapshot["as_of"], str(snapshot["shadow_direction"])))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ET)


def _resolve_outcomes(history: list[dict[str, Any]], bars_by_symbol: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    resolved = {row.get("episode_id") for row in history if row.get("record_type") == "outcome"}
    outcomes = []
    for row in history:
        if row.get("record_type") != "signal" or row.get("episode_id") in resolved:
            continue
        opened = _parse_time(str(row["as_of"])).astimezone(ET)
        if datetime.now(ET) < opened + timedelta(minutes=60):
            continue
        future = []
        for bar in bars_by_symbol.get(str(row["symbol"]), []):
            timestamp = _parse_time(str(bar["timestamp"])).astimezone(ET)
            if opened < timestamp <= opened + timedelta(minutes=60):
                future.append(bar)
        if not future:
            continue
        direction = row["shadow_direction"]
        entry = float(row["counterfactual"]["entry"])
        stop = float(row["counterfactual"]["stop"])
        target = float(row["counterfactual"]["target"])
        favorable = max(float(bar["high"]) - entry for bar in future) if direction == "call" else max(entry - float(bar["low"]) for bar in future)
        adverse = max(entry - float(bar["low"]) for bar in future) if direction == "call" else max(float(bar["high"]) - entry for bar in future)
        target_hit = any(float(bar["high"]) >= target for bar in future) if direction == "call" else any(float(bar["low"]) <= target for bar in future)
        stop_hit = any(float(bar["low"]) <= stop for bar in future) if direction == "call" else any(float(bar["high"]) >= stop for bar in future)
        outcomes.append({
            "record_type": "outcome", "episode_id": row["episode_id"],
            "symbol": row["symbol"], "opened_at": row["as_of"],
            "evaluated_at": datetime.now(ET).isoformat(), "horizon_minutes": 60,
            "max_favorable_points": round(favorable, 4),
            "max_adverse_points": round(adverse, 4),
            "target_touched": target_hit, "stop_touched": stop_hit,
            "ambiguous_same_horizon": target_hit and stop_hit,
            "authority": "shadow_research_only",
            "execution_enabled": False, "can_submit_orders": False,
        })
    return outcomes


def run(log_path: Path = LOG_PATH, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    history = _read_log(log_path)
    existing = {row.get("episode_id") for row in history if row.get("record_type") == "signal"}
    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    snapshots = []
    new_signals = []
    errors = []
    for symbol in SYMBOLS:
        try:
            bars, source = fetch_bars(symbol)
            bars_by_symbol[symbol] = bars
            snapshot = evaluate_czt(bars, symbol=symbol)
            snapshot["data_source"] = source
            snapshots.append(snapshot)
            if snapshot["czt_aligned"]:
                signal = dict(snapshot)
                signal["record_type"] = "signal"
                signal["episode_id"] = _episode_id(snapshot)
                if signal["episode_id"] not in existing:
                    new_signals.append(signal)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)[:240]})
    outcomes = _resolve_outcomes(history, bars_by_symbol)
    scan_record = {
        "record_type": "scan",
        "generated_at": datetime.now(ET).isoformat(),
        "symbols_evaluated": [row["symbol"] for row in snapshots],
        "aligned_symbols": [row["symbol"] for row in snapshots if row["czt_aligned"]],
        "errors": errors,
        "authority": "shadow_research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _append(log_path, [scan_record] + new_signals + outcomes)
    all_history = history + [scan_record] + new_signals + outcomes
    resolved_rows = [row for row in all_history if row.get("record_type") == "outcome"]
    unambiguous = [row for row in resolved_rows if not row.get("ambiguous_same_horizon")]
    wins = sum(bool(row.get("target_touched")) and not bool(row.get("stop_touched")) for row in unambiguous)
    report = {
        "generated_at": datetime.now(ET).isoformat(),
        "status": "ok" if snapshots else "error",
        "snapshots": snapshots, "errors": errors,
        "new_shadow_signals": len(new_signals), "new_outcomes": len(outcomes),
        "evidence": {
            "signals": sum(row.get("record_type") == "signal" for row in all_history),
            "resolved": len(resolved_rows), "unambiguous": len(unambiguous),
            "target_before_stop_win_rate": wins / len(unambiguous) if unambiguous else None,
        },
        "authority": "shadow_research_only",
        "execution_enabled": False, "can_submit_orders": False,
        "promotion_policy": "No execution use without preregistered forward review and human approval.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run()
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
