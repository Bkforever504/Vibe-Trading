#!/usr/bin/env python3
"""Shadow-only overnight handoff research lab.

The lab measures whether the overnight gap is followed by RTH continuation,
RTH reversal, or no useful effect. It is research only and never submits
orders or changes live bot gates.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "overnight_handoff_lab_log.jsonl"
RESULT_PATH = ROOT / "data" / "overnight_handoff_results.json"


@dataclass(frozen=True)
class SessionReturn:
    day: str
    symbol: str
    overnight_return_pct: float
    intraday_return_pct: float
    close_to_close_return_pct: float
    calendar_tag: str


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def calendar_tag(day: date) -> str:
    next_day = day + pd.offsets.BDay(1)
    prev_day = day - pd.offsets.BDay(1)
    if day.month in {3, 6, 9, 12} and next_day.month != day.month:
        return "quarter_end"
    if next_day.month != day.month:
        return "month_end"
    if prev_day.month != day.month:
        return "month_start"
    return "ordinary"


def session_returns(symbol: str, daily_bars: pd.DataFrame) -> list[SessionReturn]:
    if daily_bars.empty:
        return []
    bars = daily_bars.copy()
    bars.index = pd.to_datetime(bars.index)
    bars = bars.sort_index()
    rows: list[SessionReturn] = []
    previous_close: float | None = None
    for idx, row in bars.iterrows():
        open_price = _safe_float(row.get("open"))
        close_price = _safe_float(row.get("close"))
        if previous_close and open_price and close_price:
            day = idx.date()
            overnight = (open_price / previous_close - 1.0) * 100.0
            intraday = (close_price / open_price - 1.0) * 100.0
            close_to_close = (close_price / previous_close - 1.0) * 100.0
            rows.append(SessionReturn(
                day=day.isoformat(),
                symbol=symbol.upper(),
                overnight_return_pct=round(overnight, 4),
                intraday_return_pct=round(intraday, 4),
                close_to_close_return_pct=round(close_to_close, 4),
                calendar_tag=calendar_tag(day),
            ))
        previous_close = close_price
    return rows


def classify_handoff(overnight_return_pct: float, intraday_return_pct: float, gap_floor_pct: float) -> str:
    if abs(overnight_return_pct) < gap_floor_pct:
        return "small_gap_no_handoff"
    if overnight_return_pct == 0 or intraday_return_pct == 0:
        return "flat_followthrough"
    same_direction = (overnight_return_pct > 0) == (intraday_return_pct > 0)
    return "rth_continuation" if same_direction else "rth_reversal"


def summarize(rows: list[SessionReturn], gap_floor_pct: float = 0.35) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            "gap_floor_pct": gap_floor_pct,
            "classification_counts": {},
            "calendar_breakdown": {},
            "shadow_guidance": "insufficient_data",
        }
    enriched = []
    for row in rows:
        label = classify_handoff(row.overnight_return_pct, row.intraday_return_pct, gap_floor_pct)
        enriched.append({**row.__dict__, "handoff_classification": label})
    large = [row for row in enriched if row["handoff_classification"] != "small_gap_no_handoff"]
    reversals = [row for row in large if row["handoff_classification"] == "rth_reversal"]
    continuations = [row for row in large if row["handoff_classification"] == "rth_continuation"]
    by_class = pd.Series([row["handoff_classification"] for row in enriched]).value_counts().to_dict()
    calendar_breakdown: dict[str, dict[str, Any]] = {}
    for tag in sorted({row["calendar_tag"] for row in enriched}):
        tagged = [row for row in enriched if row["calendar_tag"] == tag]
        tagged_large = [row for row in tagged if row["handoff_classification"] != "small_gap_no_handoff"]
        calendar_breakdown[tag] = {
            "sample_count": len(tagged),
            "large_gap_count": len(tagged_large),
            "reversal_rate": round(
                sum(row["handoff_classification"] == "rth_reversal" for row in tagged_large) / len(tagged_large),
                3,
            ) if tagged_large else None,
            "avg_intraday_return_pct": round(
                sum(row["intraday_return_pct"] for row in tagged) / len(tagged),
                4,
            ) if tagged else None,
        }
    reversal_rate = len(reversals) / len(large) if large else None
    continuation_rate = len(continuations) / len(large) if large else None
    if large and reversal_rate is not None and reversal_rate >= 0.58:
        guidance = "shadow_fade_chasing_rth_breakouts_after_large_overnight_gap"
    elif large and continuation_rate is not None and continuation_rate >= 0.58:
        guidance = "shadow_respect_overnight_direction_after_large_gap"
    else:
        guidance = "no_directional_edge_from_overnight_gap_yet"
    return {
        "sample_count": len(enriched),
        "large_gap_count": len(large),
        "gap_floor_pct": gap_floor_pct,
        "classification_counts": by_class,
        "large_gap_reversal_rate": round(reversal_rate, 3) if reversal_rate is not None else None,
        "large_gap_continuation_rate": round(continuation_rate, 3) if continuation_rate is not None else None,
        "calendar_breakdown": calendar_breakdown,
        "shadow_guidance": guidance,
        "rows": enriched[-120:],
    }


def fetch_daily_bars(symbol: str, period: str) -> pd.DataFrame:
    import yfinance as yf

    data = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False)
    if data.empty:
        raise ValueError(f"no daily bars for {symbol}")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [str(col[0]).lower() for col in data.columns]
    else:
        data.columns = [str(col).lower() for col in data.columns]
    return data.rename(columns={"adj close": "adj_close"})


def build_report(symbols: list[str], period: str = "2y", gap_floor_pct: float = 0.35) -> dict[str, Any]:
    reports = []
    for symbol in symbols:
        try:
            rows = session_returns(symbol, fetch_daily_bars(symbol, period))
            report = {"symbol": symbol.upper(), "status": "ok", **summarize(rows, gap_floor_pct)}
        except Exception as exc:
            report = {"symbol": symbol.upper(), "status": "error", "error": str(exc)[:220]}
        reports.append(report)
    return {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "overnight_handoff_lab",
        "mode": "shadow_research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "symbols": reports,
        "paper_basis": [
            "Lou/Polk/Skouras 2019: overnight and intraday returns can behave like offsetting components.",
            "Bogousslavsky 2016: infrequent rebalancing can produce autocorrelation and seasonality.",
        ],
        "warnings": [
            "No broker orders are wired.",
            "This is not a 4am trading strategy.",
            "Promotion requires forward evidence and human review.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = RESULT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="SPY,QQQ,IWM")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--gap-floor-pct", type=float, default=0.35)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    report = build_report(symbols, period=args.period, gap_floor_pct=args.gap_floor_pct)
    write_report(report)
    append_log(report)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
