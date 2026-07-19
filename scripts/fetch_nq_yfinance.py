#!/usr/bin/env python3
"""Download NQ=F (E-mini Nasdaq-100) 5-minute bars via yfinance.

NQ=F is the full-size E-mini; MNQ is 1/10th. Price moves are identical —
the backtester uses raw price levels for signal generation, and P&L is
scaled by point_value. Running with --symbol MNQ gives MNQ-sized P&L on
NQ price data, which is the correct simulation.

Free limits:
  5m bars: last 60 days (yfinance limit)
  1m bars: last 7 days (yfinance limit)

Output: CSV compatible with topstep_replay_backtester.py
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance not installed. Run: pip install yfinance")

ET = ZoneInfo("America/New_York")
RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)


def fetch_and_save(
    ticker: str = "NQ=F",
    interval: str = "5m",
    period: str = "60d",
    rth_only: bool = True,
    out_path: Path | None = None,
) -> Path:
    print(f"Downloading {ticker} ({interval}, {period}) ...")
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        sys.exit(f"No data returned for {ticker}. Check ticker or try shorter period.")

    # Convert index to ET
    df.index = df.index.tz_convert(ET)

    if rth_only:
        df = df[df.index.map(lambda ts: RTH_START <= ts.time() < RTH_END)]

    if df.empty:
        sys.exit("No RTH bars after filtering. Try --no-rth to keep all sessions.")

    if out_path is None:
        slug = ticker.replace("=", "").lower()
        out_path = Path(f"examples/{slug}_{interval}_{period}.csv")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for ts, row in df.iterrows():
            writer.writerow([
                ts.strftime("%Y-%m-%dT%H:%M:%S"),
                round(float(row["Open"]), 2),
                round(float(row["High"]), 2),
                round(float(row["Low"]), 2),
                round(float(row["Close"]), 2),
                int(row["Volume"]),
            ])

    bars = len(df)
    days = df.index.normalize().nunique()
    print(f"Saved {bars} bars across {days} trading days -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch NQ=F historical bars via yfinance")
    parser.add_argument("--ticker", default="NQ=F", help="e.g. NQ=F, ES=F")
    parser.add_argument("--interval", default="5m", choices=["1m", "5m", "15m", "1h", "1d"])
    parser.add_argument("--period", default="60d", help="e.g. 7d, 30d, 60d")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-rth", dest="rth_only", action="store_false", help="Include pre/post market bars")
    args = parser.parse_args()

    out = fetch_and_save(
        ticker=args.ticker,
        interval=args.interval,
        period=args.period,
        rth_only=args.rth_only,
        out_path=args.out,
    )

    print()
    print("Run backtester with:")
    print(f"  python strategies/topstep_replay_backtester.py \\")
    print(f"    --csv {out} \\")
    print(f"    --symbol MNQ \\")
    print(f"    --range-minutes 3 \\")
    print(f"    --min-breakout-points 5.0 \\")
    print(f"    --reward-risk 1.5 \\")
    print(f"    --slippage-ticks 1 \\")
    print(f"    --commission 4.00")
    print()
    print("Note: range-minutes=3 with 5m bars = first 15 min of RTH (same as 15 x 1m bars).")


if __name__ == "__main__":
    main()
