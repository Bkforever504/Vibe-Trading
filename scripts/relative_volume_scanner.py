"""Read-only relative-volume scanner for the equity/options watchlist.

Logs symbols whose latest daily volume is unusually high versus the previous
20 sessions. This is context only: it does not place orders and should not be
used as an execution gate until the 30-day review proves value.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import data_source, fetch_ohlcv

LOG_PATH = ROOT / "data" / "relative_volume_scan_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "relative-volume-scan.json"

DEFAULT_SYMBOLS = [
    "SPY", "QQQ", "IWM", "SMH", "XLK", "XLF", "XLE", "XLV",
    "NVDA", "AMD", "AVGO", "MSFT", "AAPL", "TSLA", "PLTR",
    "COIN", "MSTR", "HOOD", "LLY", "NVO", "GME", "AMC",
]


def compute_relative_volume(symbol: str, df: Any, avg_window: int = 20) -> dict[str, Any]:
    if len(df) < avg_window + 1:
        return {
            "symbol": symbol.upper(),
            "status": "insufficient_data",
            "rows": len(df),
            "required_rows": avg_window + 1,
        }
    latest = df.iloc[-1]
    prior = df.iloc[-avg_window - 1 : -1]
    avg_volume = float(prior["volume"].mean())
    latest_volume = float(latest["volume"])
    rel_volume = latest_volume / avg_volume if avg_volume > 0 else 0.0
    prev_close = float(df.iloc[-2]["close"])
    close = float(latest["close"])
    price_change_pct = ((close / prev_close) - 1.0) * 100 if prev_close else 0.0
    if rel_volume >= 3.0:
        intensity = "extreme"
    elif rel_volume >= 2.0:
        intensity = "high"
    elif rel_volume >= 1.5:
        intensity = "elevated"
    else:
        intensity = "normal"
    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "date": str(getattr(df.index[-1], "date", lambda: df.index[-1])()),
        "close": round(close, 4),
        "price_change_pct": round(price_change_pct, 3),
        "latest_volume": round(latest_volume, 0),
        "avg_volume_20d": round(avg_volume, 0),
        "relative_volume": round(rel_volume, 3),
        "intensity": intensity,
        "context_signal": rel_volume >= 2.0,
    }


def scan_symbol(symbol: str, lookback_days: int = 90, avg_window: int = 20) -> dict[str, Any]:
    try:
        df = fetch_ohlcv(symbol.upper(), lookback_days=lookback_days)
        return compute_relative_volume(symbol, df, avg_window=avg_window)
    except Exception as exc:
        return {
            "symbol": symbol.upper(),
            "status": "error",
            "error": str(exc)[:200],
        }


def build_report(symbols: list[str] | None = None, avg_window: int = 20) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    scans = [scan_symbol(symbol, avg_window=avg_window) for symbol in symbols]
    ok = [row for row in scans if row.get("status") == "ok"]
    unusual = [row for row in ok if row.get("context_signal")]
    unusual.sort(key=lambda row: float(row.get("relative_volume") or 0), reverse=True)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "relative_volume_scanner",
        "source": data_source(),
        "mode": "context_only",
        "execution_enabled": False,
        "avg_window": avg_window,
        "symbol_count": len(scans),
        "unusual_count": len(unusual),
        "unusual_symbols": unusual,
        "scans": scans,
        "warnings": [
            "Context only. No broker orders are wired.",
            "Daily volume can be incomplete before the official close; use persistence, not a single print.",
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
    print("\nRelative Volume Scanner | context only")
    print("=" * 72)
    print(f"source={report['source']} symbols={report['symbol_count']} unusual={report['unusual_count']}")
    for row in report["unusual_symbols"][:15]:
        print(
            f"{row['symbol']:<6} rv={row['relative_volume']:<5} "
            f"chg={row['price_change_pct']:+.2f}% intensity={row['intensity']}"
        )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan watchlist for abnormal relative volume.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--avg-window", type=int, default=20)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    report = build_report(symbols=symbols, avg_window=args.avg_window)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Relative volume scan logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
