"""Read-only opening-range breadth scanner.

Checks how many liquid watchlist names broke above/below the 9:30-9:35 ET
opening range. This helps diagnose trend-day breadth before options bots act.
No orders, no execution gates.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "opening_range_breadth_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "opening-range-breadth.json"

DEFAULT_SYMBOLS = [
    "SPY", "QQQ", "IWM", "SMH", "XLK", "XLF", "XLE", "XLV",
    "NVDA", "AMD", "AVGO", "MSFT", "AAPL", "TSLA", "PLTR",
    "COIN", "MSTR", "HOOD", "LLY", "NVO",
]


def fetch_intraday_bars_alpaca(symbol: str, trading_day: date | None = None) -> pd.DataFrame:
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError as exc:
        raise ImportError("alpaca-py required for opening-range breadth scanner") from exc

    import scripts.market_data as market_data

    market_data._load_env()  # noqa: SLF001 - operational helper shared by local scanners
    if not (market_data._ALPACA_KEY and market_data._ALPACA_SECRET):  # noqa: SLF001
        raise RuntimeError("ALPACA_API_KEY/ALPACA_SECRET_KEY required for intraday bars")

    trading_day = trading_day or date.today()
    eastern = ZoneInfo("America/New_York")
    start_dt = datetime.combine(trading_day, time(9, 30), tzinfo=eastern)
    end_dt = datetime.combine(trading_day, time(16, 0), tzinfo=eastern)
    client = StockHistoricalDataClient(api_key=market_data._ALPACA_KEY, secret_key=market_data._ALPACA_SECRET)  # noqa: SLF001
    request = StockBarsRequest(
        symbol_or_symbols=symbol.upper(),
        timeframe=TimeFrame.Minute,
        start=start_dt,
        end=end_dt,
        adjustment="raw",
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)
    df = bars.df
    if df.empty:
        raise ValueError(f"No Alpaca intraday bars for {symbol}")
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol.upper(), level="symbol")
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    df.columns = [str(c).lower() for c in df.columns]
    return df[[c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]].dropna().copy()


def compute_opening_range_signal(symbol: str, df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"symbol": symbol.upper(), "status": "empty"}
    eastern_index = pd.to_datetime(df.index)
    if eastern_index.tz is None:
        eastern_index = eastern_index.tz_localize("America/New_York")
    else:
        eastern_index = eastern_index.tz_convert("America/New_York")
    working = df.copy()
    working.index = eastern_index
    open_window = working.between_time("09:30", "09:34")
    post_window = working.between_time("09:35", "16:00")
    if open_window.empty or post_window.empty:
        return {
            "symbol": symbol.upper(),
            "status": "insufficient_data",
            "bars": len(working),
            "opening_bars": len(open_window),
            "post_bars": len(post_window),
        }
    or_high = float(open_window["high"].max())
    or_low = float(open_window["low"].min())
    latest = post_window.iloc[-1]
    latest_close = float(latest["close"])
    broke_up = bool((post_window["close"] > or_high).any())
    broke_down = bool((post_window["close"] < or_low).any())
    if latest_close > or_high:
        state = "above_opening_range"
    elif latest_close < or_low:
        state = "below_opening_range"
    else:
        state = "inside_opening_range"
    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "date": working.index[-1].date().isoformat(),
        "opening_range_high": round(or_high, 4),
        "opening_range_low": round(or_low, 4),
        "latest_close": round(latest_close, 4),
        "broke_up": broke_up,
        "broke_down": broke_down,
        "state": state,
    }


def scan_symbol(symbol: str, trading_day: date | None = None) -> dict[str, Any]:
    try:
        return compute_opening_range_signal(symbol, fetch_intraday_bars_alpaca(symbol, trading_day=trading_day))
    except Exception as exc:
        return {
            "symbol": symbol.upper(),
            "status": "error",
            "error": str(exc)[:200],
        }


def aggregate_breadth(scans: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in scans if row.get("status") == "ok"]
    if not ok:
        return {"bias": "unavailable", "ok_count": 0}
    above = sum(1 for row in ok if row.get("state") == "above_opening_range")
    below = sum(1 for row in ok if row.get("state") == "below_opening_range")
    inside = sum(1 for row in ok if row.get("state") == "inside_opening_range")
    breadth_score = (above - below) / len(ok)
    if breadth_score >= 0.35:
        bias = "bullish_breadth"
    elif breadth_score <= -0.35:
        bias = "bearish_breadth"
    else:
        bias = "mixed"
    return {
        "bias": bias,
        "ok_count": len(ok),
        "above_count": above,
        "below_count": below,
        "inside_count": inside,
        "breadth_score": round(breadth_score, 3),
    }


_NYSE_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 7, 4), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 11, 27), date(2026, 12, 25),
}


def _is_market_closed(d: date) -> bool:
    return d.weekday() >= 5 or d in _NYSE_HOLIDAYS


def build_report(symbols: list[str] | None = None, trading_day: date | None = None) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    trading_day = trading_day or date.today()
    if _is_market_closed(trading_day):
        return {
            "date": trading_day.isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "provider": "opening_range_breadth_scanner",
            "status": "market_closed",
            "mode": "context_only",
            "execution_enabled": False,
            "symbol_count": 0,
            "scans": [],
        }
    scans = [scan_symbol(symbol, trading_day=trading_day) for symbol in symbols]
    return {
        "date": trading_day.isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "opening_range_breadth_scanner",
        "source": "alpaca_intraday_bars",
        "mode": "context_only",
        "execution_enabled": False,
        "symbol_count": len(scans),
        "aggregate": aggregate_breadth(scans),
        "scans": scans,
        "warnings": [
            "Context only. No broker orders are wired.",
            "Use after 09:40 ET; earlier runs may not have enough post-opening-range bars.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nOpening Range Breadth | context only")
    print("=" * 72)
    if report.get("status") == "market_closed":
        print(f"status=market_closed date={report.get('date')} scans=0")
        print("No orders placed.\n")
        return
    agg = report["aggregate"]
    print(
        f"bias={agg.get('bias')} score={agg.get('breadth_score')} "
        f"above={agg.get('above_count', 0)} below={agg.get('below_count', 0)} inside={agg.get('inside_count', 0)}"
    )
    for row in report["scans"][:12]:
        if row.get("status") != "ok":
            print(f"{row['symbol']:<6} {row.get('status')} {row.get('error', '')}")
        else:
            print(f"{row['symbol']:<6} {row['state']:<22} close={row['latest_close']}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan watchlist opening-range breadth.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, default today")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    trading_day = date.fromisoformat(args.date) if args.date else None
    report = build_report(symbols=symbols, trading_day=trading_day)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Opening range breadth logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
