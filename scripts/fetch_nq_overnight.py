#!/usr/bin/env python3
"""Fetch NQ=F 1h bars including extended hours (prepost=True) and save overnight subset.

Overnight bars: time < 09:30 ET (pre-market) or time >= 16:00 ET (after-hours).
Output CSV: date (the RTH date the overnight session precedes), overnight_high, overnight_low.

Usage:
    uv run --no-project --with yfinance python scripts/fetch_nq_overnight.py
    uv run --no-project --with yfinance python scripts/fetch_nq_overnight.py --period 60d --out examples/nq_1h_overnight.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance not installed. Run: pip install yfinance")

ET = ZoneInfo("America/New_York")
RTH_START = dtime(9, 30)
RTH_END   = dtime(16, 0)

DEFAULT_OUT = Path("examples/nq_1h_overnight.csv")


def _rth_date_for_bar(ts: datetime) -> date:
    """Return the RTH trading date that this overnight bar belongs to.

    Pre-market bars (time < 09:30) belong to the same calendar date.
    After-hours bars (time >= 16:00) belong to the NEXT trading date.
    """
    if ts.time() >= RTH_END:
        # After-hours: part of the next session
        return (ts + timedelta(days=1)).date()
    return ts.date()


def fetch_overnight(ticker: str = "NQ=F", period: str = "730d") -> dict[str, dict[str, float]]:
    """Return {rth_date_str: {overnight_high, overnight_low}} from prepost bars."""
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval="1h", auto_adjust=True, prepost=True)
    if df.empty:
        return {}

    df.index = df.index.tz_convert(ET)

    sessions: dict[str, list[dict]] = {}
    for ts, row in df.iterrows():
        bar_time = ts.time()
        # Keep only overnight bars (pre-market or after-hours)
        if RTH_START <= bar_time < RTH_END:
            continue
        rth_date = _rth_date_for_bar(ts).isoformat()
        sessions.setdefault(rth_date, []).append({
            "high": float(row["High"]),
            "low":  float(row["Low"]),
        })

    result: dict[str, dict[str, float]] = {}
    for date_str, bars in sessions.items():
        result[date_str] = {
            "overnight_high": max(b["high"] for b in bars),
            "overnight_low":  min(b["low"]  for b in bars),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch NQ=F overnight H/L levels")
    parser.add_argument("--ticker",  default="NQ=F")
    parser.add_argument("--period",  default="730d", help="yfinance period string")
    parser.add_argument("--out",     type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    print(f"Fetching {args.ticker} extended-hours 1h bars (period={args.period})...")
    data = fetch_overnight(args.ticker, args.period)
    if not data:
        print("No overnight bars returned.")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    dates = sorted(data.keys())
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "overnight_high", "overnight_low"])
        writer.writeheader()
        for d in dates:
            writer.writerow({"date": d, **data[d]})

    print(f"Saved {len(dates)} overnight sessions → {args.out}")
    print(f"Date range: {dates[0]} → {dates[-1]}")


if __name__ == "__main__":
    main()
