#!/usr/bin/env python3
"""Chart-first recall audit for a fixed, liquid intraday universe.

This makes raw completed 5m price movement the denominator, then asks whether
the intraday radar had discovered or confirmed each move by the time it ended.
It is read-only and records no fills, options contracts, or trading actions.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.intraday_opportunity_radar import CORE_LIQUID_SYMBOLS, MARKET_TZ, fetch_intraday_bars
from scripts.premarket_opportunity_radar import _atomic_json

VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "liquid-universe-recall.json"
LEDGER_PATH = ROOT / "data" / "liquid_universe_recall.jsonl"
UNIVERSE = tuple(dict.fromkeys((*CORE_LIQUID_SYMBOLS, "SMH", "XLK", "XLF", "XLE", "XLV", "GLD")))


def _history(session: str) -> list[dict[str, Any]]:
    try: rows = [json.loads(line) for line in RADAR_LOG.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError): return []
    return sorted((row for row in rows if isinstance(row, dict) and str(row.get("date") or "")[:10] == session), key=lambda row: str(row.get("as_of_et") or ""))


def _fetch(now_et: datetime) -> tuple[dict[str, pd.DataFrame], list[str]]:
    try:
        import yfinance as yf
        raw = yf.download(list(UNIVERSE), period="1d", interval="5m", group_by="ticker", prepost=False, progress=False, threads=True, auto_adjust=True)
    except Exception as exc: return {}, [f"yfinance_liquid_recall:{type(exc).__name__}"]
    output: dict[str, pd.DataFrame] = {}
    for symbol in UNIVERSE:
        try:
            frame = raw[symbol].dropna(subset=["Open", "High", "Low", "Close"])
            idx = pd.to_datetime(frame.index, utc=True).tz_convert(MARKET_TZ)
            frame = frame.copy(); frame.index = idx
            frame = frame[(frame.index.time >= time(9, 30)) & (frame.index.time < time(16)) & (frame.index <= now_et)]
            if len(frame) >= 4: output[symbol] = frame
        except (KeyError, TypeError, ValueError): continue
    if output:
        return output, []
    # Keep the audit live if yfinance's local cache fails.  The fallback is
    # explicitly the same IEX completed-bar feed used by the intraday radar.
    raw_bars, errors = fetch_intraday_bars(list(UNIVERSE), now_et)
    for symbol, rows in raw_bars.items():
        try:
            frame = pd.DataFrame(rows)
            frame.index = pd.to_datetime(frame["t"], utc=True).dt.tz_convert(MARKET_TZ)
            frame = frame.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
            frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
            if len(frame) >= 4: output[symbol] = frame
        except (KeyError, TypeError, ValueError):
            continue
    return output, ["yfinance_unavailable_used_alpaca_iex_fallback", *errors]


def chart_moves(symbol: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
    threshold = 0.20 if symbol in {"SPY", "QQQ", "IWM", "DIA", "GLD", "XLF", "XLK", "XLE", "XLV", "SMH"} else 0.35
    close = frame["Close"].astype(float).to_numpy(); index = frame.index; moves = []; last_end = {"bullish": -1, "bearish": -1}
    for start in range(len(close) - 3):
        end = start + 3  # 15-minute completed move.
        change = (close[end] / close[start] - 1) * 100
        direction = "bullish" if change > 0 else "bearish"
        if abs(change) < threshold or start <= last_end[direction]: continue
        moves.append({"symbol": symbol, "direction": direction, "start_at": index[start].isoformat(), "end_at": index[end].isoformat(), "return_pct": round(change, 4), "threshold_pct": threshold})
        last_end[direction] = end
    return moves


def _when(value: Any) -> datetime | None:
    try: return pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError): return None


def audit_move(move: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    end = _when(move["end_at"]); symbol = move["symbol"]
    before = [row for row in history if (_when(row.get("as_of_et")) or datetime.min.replace(tzinfo=timezone.utc)) <= end]
    discovered = None; confirmed = None; opposing_confirmation = None
    for snapshot in before:
        stamp = snapshot.get("as_of_et")
        if symbol in [str(x).upper() for x in snapshot.get("all_discovered_symbols") or []]: discovered = discovered or stamp
        for candidate in snapshot.get("ranked_candidates") or []:
            if isinstance(candidate, dict) and str(candidate.get("symbol") or "").upper() == symbol:
                discovered = discovered or stamp
                if str(candidate.get("confirmation_stage") or "") == "completed_5m_confirmed":
                    if str(candidate.get("direction") or "") == str(move.get("direction") or ""):
                        confirmed = confirmed or stamp
                    else:
                        opposing_confirmation = opposing_confirmation or stamp
    classification = "confirmed" if confirmed else "opposing_confirmation" if opposing_confirmation else "discovered_only" if discovered else "missed"
    return {**move, "discovered_by_move_end": discovered is not None, "confirmed_by_move_end": confirmed is not None, "opposing_confirmation_by_move_end": opposing_confirmation is not None, "first_discovered_at": discovered, "first_confirmed_at": confirmed, "first_opposing_confirmation_at": opposing_confirmation, "classification": classification}


def build_report(now_et: datetime | None = None) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    history = _history(now_et.date().isoformat()); frames, errors = _fetch(now_et)
    moves = [audit_move(move, history) for symbol, frame in frames.items() for move in chart_moves(symbol, frame)]
    counts = {key: sum(row["classification"] == key for row in moves) for key in ("confirmed", "opposing_confirmation", "discovered_only", "missed")}
    return {"schema_version": 2, "date": now_et.date().isoformat(), "as_of_et": now_et.isoformat(), "mode": "chart_first_liquid_universe_recall", "execution_enabled": False, "can_submit_orders": False, "universe": list(UNIVERSE), "definition": "15m completed close-to-close move; ETF threshold 0.20%, single-stock threshold 0.35%; confirmation must match direction by move end", "summary": {"universe_symbols_with_chart_data": len(frames), "radar_snapshots": len(history), "moves": len(moves), "confirmed_directional_recall_pct": round(counts["confirmed"] / len(moves) * 100, 2) if moves else None, "discovery_recall_pct": round((counts["confirmed"] + counts["opposing_confirmation"] + counts["discovered_only"]) / len(moves) * 100, 2) if moves else None, "counts": counts}, "moves": moves, "errors": errors, "warnings": ["Chart moves are a coverage denominator, not trading signals.", "Confirmation is counted only when the scanner direction matches the realized chart move by its completed end time.", "No fill, option premium, transaction cost, or profitability is inferred.", "A miss is an operational research item, not permission to loosen risk gates."]}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--report-path", type=Path, default=REPORT_PATH); parser.add_argument("--ledger-path", type=Path, default=LEDGER_PATH); parser.add_argument("--print", action="store_true", dest="show"); args = parser.parse_args()
    report = build_report(); _atomic_json(args.report_path, report); args.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger_path.open("a", encoding="utf-8") as handle: handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    print(json.dumps(report, indent=2) if args.show else f"Liquid recall: moves={report['summary']['moves']} confirmed={report['summary']['counts']['confirmed']} missed={report['summary']['counts']['missed']}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
