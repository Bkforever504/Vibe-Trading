"""Read-only market breadth and uptrend analyzer.

Measures broad participation across liquid ETFs/large-cap leaders:
- percent above 20/50/200-day moving averages
- daily advancers vs decliners
- sector/defensive relative strength

This is a regime layer only. It does not trade.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import data_source, fetch_close

LOG_PATH = ROOT / "data" / "market_breadth_uptrend_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "market-breadth-uptrend.json"

BREADTH_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLU",
    "GLD", "TLT", "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "META", "AMZN", "GOOGL", "TSLA", "PLTR",
    "COIN", "MSTR", "HOOD", "LLY", "NVO", "JPM", "BAC", "UNH", "COST", "WMT",
]
DEFENSIVE_SYMBOLS = ["XLU", "XLP", "GLD", "TLT"]
LEADERSHIP_SYMBOLS = ["QQQ", "SMH", "XLK", "NVDA", "AVGO", "MSFT", "AAPL"]


def _pct_above(values: list[bool]) -> float:
    return round(sum(1 for value in values if value) / len(values) * 100, 2) if values else 0.0


def compute_breadth(close: pd.DataFrame) -> dict[str, Any]:
    if close.empty or len(close) < 201:
        return {"status": "insufficient_data", "rows": len(close), "required_rows": 201}
    latest = close.iloc[-1]
    prev = close.iloc[-2]
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    valid = [sym for sym in close.columns if pd.notna(latest.get(sym)) and pd.notna(sma200.get(sym))]

    above20 = {sym: bool(latest[sym] > sma20[sym]) for sym in valid}
    above50 = {sym: bool(latest[sym] > sma50[sym]) for sym in valid}
    above200 = {sym: bool(latest[sym] > sma200[sym]) for sym in valid}
    advancers = {sym: bool(latest[sym] > prev[sym]) for sym in valid if pd.notna(prev.get(sym))}

    spy_20d = _return_pct(close["SPY"], 20) if "SPY" in close.columns else None
    defensive_returns = {
        sym: _return_pct(close[sym], 20)
        for sym in DEFENSIVE_SYMBOLS
        if sym in close.columns and close[sym].dropna().shape[0] >= 21
    }
    defensive_outperformers = [
        sym for sym, ret in defensive_returns.items()
        if spy_20d is not None and ret > spy_20d
    ]
    leadership_above50 = [sym for sym in LEADERSHIP_SYMBOLS if above50.get(sym)]

    pct50 = _pct_above(list(above50.values()))
    pct200 = _pct_above(list(above200.values()))
    adv_pct = _pct_above(list(advancers.values()))

    if pct50 >= 65 and pct200 >= 60 and adv_pct >= 50:
        uptrend = "confirmed_uptrend"
    elif pct50 >= 45 and pct200 >= 45:
        uptrend = "uptrend_under_pressure"
    elif pct50 < 35 or pct200 < 40:
        uptrend = "correction"
    else:
        uptrend = "mixed"

    return {
        "status": "ok",
        "symbol_count": len(valid),
        "as_of": str(getattr(close.index[-1], "date", lambda: close.index[-1])()),
        "pct_above_20dma": _pct_above(list(above20.values())),
        "pct_above_50dma": pct50,
        "pct_above_200dma": pct200,
        "advancer_pct": adv_pct,
        "uptrend_status": uptrend,
        "leadership_above_50dma": leadership_above50,
        "leadership_count": len(leadership_above50),
        "defensive_outperformers_20d": defensive_outperformers,
        "defensive_outperformer_count": len(defensive_outperformers),
        "spy_20d_return_pct": spy_20d,
        "defensive_returns_20d": defensive_returns,
    }


def _return_pct(series: pd.Series, lookback: int) -> float:
    clean = series.dropna()
    if len(clean) <= lookback:
        return 0.0
    return round(((float(clean.iloc[-1]) / float(clean.iloc[-lookback - 1])) - 1.0) * 100, 3)


def force_score(breadth: dict[str, Any]) -> float:
    if breadth.get("status") != "ok":
        return 0.0
    status = breadth.get("uptrend_status")
    score = {
        "confirmed_uptrend": 2.0,
        "uptrend_under_pressure": 0.5,
        "mixed": 0.0,
        "correction": -2.0,
    }.get(str(status), 0.0)
    if int(breadth.get("defensive_outperformer_count") or 0) >= 2:
        score -= 0.75
    if int(breadth.get("leadership_count") or 0) >= 5:
        score += 0.5
    return round(max(-2.5, min(2.5, score)), 3)


def build_report(symbols: list[str] | None = None) -> dict[str, Any]:
    symbols = symbols or BREADTH_UNIVERSE
    close = fetch_close(symbols, lookback_days=420)
    breadth = compute_breadth(close)
    score = force_score(breadth)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "market_breadth_uptrend_scanner",
        "source": data_source(),
        "mode": "context_only",
        "execution_enabled": False,
        "breadth": breadth,
        "force_score": score,
        "warnings": [
            "Context only. No broker orders are wired.",
            "Breadth should guide posture, not override trade guards.",
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
    breadth = report["breadth"]
    print("\nMarket Breadth / Uptrend | context only")
    print("=" * 72)
    if breadth.get("status") != "ok":
        print(
            f"status={breadth.get('status')} rows={breadth.get('rows')} "
            f"required={breadth.get('required_rows')} source={report['source']}"
        )
        print("No orders placed.\n")
        return
    print(
        f"status={breadth.get('uptrend_status')} force={report['force_score']} "
        f"above50={breadth.get('pct_above_50dma')} above200={breadth.get('pct_above_200dma')} "
        f"adv={breadth.get('advancer_pct')}"
    )
    print(
        f"leadership={breadth.get('leadership_count')} defensive={breadth.get('defensive_outperformer_count')} "
        f"source={report['source']}"
    )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan market breadth/uptrend participation.")
    parser.add_argument("--symbols", default=",".join(BREADTH_UNIVERSE))
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    report = build_report(symbols=symbols)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Market breadth/uptrend scan logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
