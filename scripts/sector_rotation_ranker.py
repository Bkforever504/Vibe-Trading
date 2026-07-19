"""Read-only US sector rotation ranker.

Inspired by the alpha/sector ranking pattern in trading-skills, adapted for
our US/Alpaca stack. This does not trade; it logs leadership quality.
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

LOG_PATH = ROOT / "data" / "sector_rotation_rank_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "sector-rotation-rank.json"

SECTOR_UNIVERSE = [
    "SPY", "QQQ", "IWM", "SMH",
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLU", "XLI", "XLB", "XLRE",
    "GLD", "TLT",
]
RISK_ON = {"QQQ", "IWM", "SMH", "XLK", "XLY", "XLF", "XLE", "XLI", "XLB"}
DEFENSIVE = {"XLP", "XLU", "XLV", "GLD", "TLT", "XLRE"}


def _return_pct(series: pd.Series, lookback: int) -> float | None:
    clean = series.dropna()
    if len(clean) <= lookback:
        return None
    return round(((float(clean.iloc[-1]) / float(clean.iloc[-lookback - 1])) - 1.0) * 100.0, 3)


def compute_rankings(close: pd.DataFrame) -> dict[str, Any]:
    if close.empty or len(close) < 51:
        return {"status": "insufficient_data", "rows": len(close), "required_rows": 51}
    latest = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    spy_ret_20 = _return_pct(close["SPY"], 20) if "SPY" in close.columns else None
    rows = []
    for symbol in close.columns:
        series = close[symbol]
        if series.dropna().shape[0] < 51:
            continue
        ret1 = _return_pct(series, 1)
        ret5 = _return_pct(series, 5)
        ret20 = _return_pct(series, 20)
        if ret1 is None or ret5 is None or ret20 is None:
            continue
        above50 = bool(pd.notna(latest.get(symbol)) and pd.notna(sma50.get(symbol)) and latest[symbol] > sma50[symbol])
        rel20 = round(ret20 - spy_ret_20, 3) if spy_ret_20 is not None and symbol != "SPY" else 0.0
        score = ret20 + (0.5 * ret5) + (0.25 * ret1) + (2.0 if above50 else -2.0) + rel20
        rows.append({
            "symbol": symbol,
            "return_1d_pct": ret1,
            "return_5d_pct": ret5,
            "return_20d_pct": ret20,
            "relative_to_spy_20d_pct": rel20,
            "above_50dma": above50,
            "rotation_score": round(score, 3),
            "bucket": "risk_on" if symbol in RISK_ON else "defensive" if symbol in DEFENSIVE else "benchmark",
        })
    ranked = sorted(rows, key=lambda row: float(row["rotation_score"]), reverse=True)
    top5 = ranked[:5]
    bottom5 = ranked[-5:]
    risk_on_top = sum(1 for row in top5 if row["bucket"] == "risk_on")
    defensive_top = sum(1 for row in top5 if row["bucket"] == "defensive")
    if risk_on_top >= 3:
        leadership = "risk_on_leadership"
        force = 1.5
    elif defensive_top >= 3:
        leadership = "defensive_rotation"
        force = -1.5
    elif risk_on_top > defensive_top:
        leadership = "risk_on_lean"
        force = 0.75
    elif defensive_top > risk_on_top:
        leadership = "defensive_lean"
        force = -0.75
    else:
        leadership = "mixed"
        force = 0.0
    return {
        "status": "ok",
        "as_of": str(getattr(close.index[-1], "date", lambda: close.index[-1])()),
        "symbol_count": len(ranked),
        "leadership": leadership,
        "force_score": force,
        "risk_on_top5_count": risk_on_top,
        "defensive_top5_count": defensive_top,
        "top5": top5,
        "bottom5": bottom5,
        "rankings": ranked,
    }


def build_report(symbols: list[str] | None = None) -> dict[str, Any]:
    symbols = symbols or SECTOR_UNIVERSE
    close = fetch_close(symbols, lookback_days=140)
    rotation = compute_rankings(close)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "sector_rotation_ranker",
        "source": data_source(),
        "mode": "context_only",
        "execution_enabled": False,
        "rotation": rotation,
        "force_score": float(rotation.get("force_score") or 0.0),
        "warnings": [
            "Context only. No broker orders are wired.",
            "Use leadership as posture evidence, not a direct entry signal.",
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
    rotation = report["rotation"]
    print("\nSector Rotation Ranker | context only")
    print("=" * 72)
    if rotation.get("status") != "ok":
        print(f"status={rotation.get('status')} rows={rotation.get('rows')} required={rotation.get('required_rows')}")
        print("No orders placed.\n")
        return
    top = ", ".join(f"{row['symbol']}({row['rotation_score']})" for row in rotation["top5"])
    bottom = ", ".join(f"{row['symbol']}({row['rotation_score']})" for row in rotation["bottom5"])
    print(
        f"leadership={rotation['leadership']} force={report['force_score']} "
        f"risk_on_top5={rotation['risk_on_top5_count']} defensive_top5={rotation['defensive_top5_count']} "
        f"source={report['source']}"
    )
    print(f"top5: {top}")
    print(f"bottom5: {bottom}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank US sector/asset leadership.")
    parser.add_argument("--symbols", default=",".join(SECTOR_UNIVERSE))
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
        print(f"Sector rotation rank logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
