"""Read-only IBD-style distribution day scanner.

Counts institutional selling pressure on SPY/QQQ. A distribution day is a down
day on higher volume. This is a market-regime context layer only.
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

LOG_PATH = ROOT / "data" / "distribution_day_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "distribution-day-scan.json"
DEFAULT_SYMBOLS = ["QQQ", "SPY"]


def compute_distribution_days(df: Any, lookback_sessions: int = 25, min_down_pct: float = 0.2) -> dict[str, Any]:
    if len(df) < lookback_sessions + 2:
        return {"status": "insufficient_data", "rows": len(df), "required_rows": lookback_sessions + 2}
    working = df.tail(lookback_sessions + 1).copy()
    events = []
    for idx in range(1, len(working)):
        row = working.iloc[idx]
        prev = working.iloc[idx - 1]
        prev_close = float(prev["close"])
        close = float(row["close"])
        pct_change = ((close / prev_close) - 1.0) * 100 if prev_close else 0.0
        higher_volume = float(row["volume"]) > float(prev["volume"])
        is_distribution = pct_change <= -abs(min_down_pct) and higher_volume
        if is_distribution:
            events.append({
                "date": str(getattr(working.index[idx], "date", lambda: working.index[idx])()),
                "close": round(close, 4),
                "pct_change": round(pct_change, 3),
                "volume": round(float(row["volume"]), 0),
                "prior_volume": round(float(prev["volume"]), 0),
            })
    count = len(events)
    if count >= 7:
        regime = "severe"
    elif count >= 5:
        regime = "high"
    elif count >= 3:
        regime = "caution"
    else:
        regime = "normal"
    return {
        "status": "ok",
        "lookback_sessions": lookback_sessions,
        "distribution_day_count": count,
        "regime": regime,
        "events": events,
    }


def scan_symbol(symbol: str, lookback_sessions: int = 25) -> dict[str, Any]:
    try:
        df = fetch_ohlcv(symbol, lookback_days=80)
        result = compute_distribution_days(df, lookback_sessions=lookback_sessions)
        return {"symbol": symbol.upper(), **result}
    except Exception as exc:
        return {"symbol": symbol.upper(), "status": "error", "error": str(exc)[:200]}


def aggregate_regime(scans: list[dict[str, Any]]) -> dict[str, Any]:
    ranks = {"normal": 0, "caution": 1, "high": 2, "severe": 3}
    ok = [scan for scan in scans if scan.get("status") == "ok"]
    if not ok:
        return {"regime": "unavailable", "ok_count": 0, "max_distribution_days": 0}
    worst = max(ok, key=lambda row: ranks.get(str(row.get("regime")), -1))
    max_count = max(int(row.get("distribution_day_count") or 0) for row in ok)
    return {
        "regime": worst.get("regime", "normal"),
        "ok_count": len(ok),
        "max_distribution_days": max_count,
        "symbol_regimes": {row["symbol"]: row.get("regime") for row in ok},
    }


def build_report(symbols: list[str] | None = None, lookback_sessions: int = 25) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    scans = [scan_symbol(symbol, lookback_sessions=lookback_sessions) for symbol in symbols]
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "distribution_day_scanner",
        "source": data_source(),
        "mode": "context_only",
        "execution_enabled": False,
        "aggregate": aggregate_regime(scans),
        "scans": scans,
        "warnings": [
            "Context only. No broker orders are wired.",
            "Distribution days are market-regime evidence, not standalone short signals.",
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
    agg = report["aggregate"]
    print("\nDistribution Day Scanner | context only")
    print("=" * 72)
    print(f"regime={agg.get('regime')} max_count={agg.get('max_distribution_days')} source={report['source']}")
    for scan in report["scans"]:
        print(f"{scan['symbol']:<5} status={scan.get('status')} count={scan.get('distribution_day_count')} regime={scan.get('regime')}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan QQQ/SPY distribution days.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--lookback-sessions", type=int, default=25)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    report = build_report(symbols=symbols, lookback_sessions=args.lookback_sessions)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Distribution day scan logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
