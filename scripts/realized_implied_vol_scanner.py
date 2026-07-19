#!/usr/bin/env python3
"""Realized-vs-implied volatility regime scanner.

Context only. Uses recent realized volatility from daily bars and ATM implied
volatility from the IVR scanner to classify which strategy family the tape most
likely favors:

- RV/IV >= 1.20: realized movement is outrunning implied vol -> momentum/breakout context
- RV/IV <= 0.80: implied vol is rich vs realized movement -> premium/mean-reversion context
- otherwise: no strong volatility-family edge

This report never places orders and must not become an execution gate without
the normal 30-day / 10-sample promotion review.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "rv_iv_regime_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "rv-iv-regime.json"
IVR_LOG_PATH = ROOT / "data" / "iv_history_log.jsonl"

SYMBOLS = ["SPY", "QQQ", "IWM"]
RV_WINDOWS = [10, 20]
MOMENTUM_THRESHOLD = 1.20
MEAN_REVERSION_THRESHOLD = 0.80


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def latest_ivr_for_day(day: str, path: Path = IVR_LOG_PATH) -> dict[str, dict[str, Any]]:
    matches = [row for row in _read_jsonl(path) if str(row.get("date", ""))[:10] == day]
    if not matches:
        return {}
    latest = matches[-1]
    out: dict[str, dict[str, Any]] = {}
    for scan in latest.get("scans", []):
        if isinstance(scan, dict) and scan.get("symbol"):
            out[str(scan["symbol"])] = scan
    return out


def realized_vol_from_closes(closes: list[float], window: int) -> float | None:
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1):]
    returns: list[float] = []
    for prev, cur in zip(tail, tail[1:]):
        if prev <= 0 or cur <= 0:
            return None
        returns.append(math.log(cur / prev))
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def classify_ratio(ratio: float | None) -> tuple[str, str, float]:
    if ratio is None:
        return "unavailable", "no_context", 0.0
    if ratio >= MOMENTUM_THRESHOLD:
        return "realized_over_implied", "momentum_breakout", 1.0
    if ratio <= MEAN_REVERSION_THRESHOLD:
        return "implied_over_realized", "premium_mean_reversion", -1.0
    return "balanced", "stand_aside_or_confirm", 0.0


def scan_symbol(symbol: str, *, day: str, ivr_by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ivr_scan = ivr_by_symbol.get(symbol, {})
    atm_iv = ivr_scan.get("atm_iv")
    try:
        implied_vol = float(atm_iv) if atm_iv is not None else None
    except (TypeError, ValueError):
        implied_vol = None
    if implied_vol is None or implied_vol <= 0:
        return {
            "symbol": symbol,
            "status": "unavailable",
            "error": "missing_atm_iv_from_ivr_scanner",
            "regime": "unavailable",
            "bias": "no_context",
            "score": 0.0,
        }

    try:
        from scripts import market_data

        df = market_data.fetch_ohlcv(symbol, lookback_days=90)
        closes = [float(value) for value in df["close"].dropna().tolist()]
        data_source = market_data.data_source()
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "error",
            "error": str(exc)[:180],
            "implied_vol": round(implied_vol, 4),
            "regime": "unavailable",
            "bias": "no_context",
            "score": 0.0,
        }

    rv_values: dict[str, float | None] = {}
    for window in RV_WINDOWS:
        rv = realized_vol_from_closes(closes, window)
        rv_values[f"rv_{window}d"] = round(rv, 4) if rv is not None else None
    primary_rv = rv_values.get("rv_20d") or rv_values.get("rv_10d")
    ratio = round(float(primary_rv) / implied_vol, 3) if primary_rv is not None else None
    regime, bias, score = classify_ratio(ratio)
    return {
        "symbol": symbol,
        "status": "ok",
        "data_source": data_source,
        "implied_vol": round(implied_vol, 4),
        "implied_vol_pct": round(implied_vol * 100, 2),
        **rv_values,
        "rv_iv_ratio": ratio,
        "regime": regime,
        "bias": bias,
        "score": score,
        "ivr_status": ivr_scan.get("status"),
        "date": day,
    }


def aggregate(scans: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [scan for scan in scans if scan.get("status") == "ok"]
    ratio_scans = [
        scan for scan in ok
        if isinstance(scan.get("rv_iv_ratio"), int | float)
    ]
    if not ratio_scans:
        return {
            "status": "unavailable",
            "regime": "unavailable",
            "bias": "no_context",
            "avg_ratio": None,
            "score": 0.0,
            "votes": {},
            "ok_symbols": 0,
            "status_ok_symbols": len(ok),
        }
    avg_ratio = sum(float(scan["rv_iv_ratio"]) for scan in ratio_scans) / len(ratio_scans)
    votes: dict[str, int] = {}
    for scan in ratio_scans:
        votes[str(scan.get("bias"))] = votes.get(str(scan.get("bias")), 0) + 1
    bias = max(votes, key=votes.get)
    regime, _bias_from_ratio, score = classify_ratio(avg_ratio)
    return {
        "status": "ok",
        "regime": regime,
        "bias": bias if votes.get(bias, 0) >= 2 else _bias_from_ratio,
        "avg_ratio": round(avg_ratio, 3),
        "score": score,
        "votes": votes,
        "ok_symbols": len(ratio_scans),
        "status_ok_symbols": len(ok),
    }


def build_report(day: str | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    symbols = symbols or SYMBOLS
    ivr_by_symbol = latest_ivr_for_day(day)
    scans = [scan_symbol(symbol, day=day, ivr_by_symbol=ivr_by_symbol) for symbol in symbols]
    agg = aggregate(scans)
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "rv_iv_regime",
        "mode": "read_only",
        "execution_enabled": False,
        "thresholds": {
            "momentum_breakout": MOMENTUM_THRESHOLD,
            "premium_mean_reversion": MEAN_REVERSION_THRESHOLD,
        },
        "aggregate": agg,
        "scans": scans,
        "source_paths": {"ivr": str(IVR_LOG_PATH)},
        "warnings": [
            "Context only. No orders are placed.",
            "Thresholds are research hypotheses, not an execution gate.",
            "Use 30 trading days / 10 relevant samples before allowing this to affect trade gating.",
        ],
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")
    return path


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    agg = report["aggregate"]
    print("\nRV/IV Regime Scanner | read-only")
    print("=" * 72)
    print(
        f"{report['date']} regime={agg.get('regime')} bias={agg.get('bias')} "
        f"avg_ratio={agg.get('avg_ratio')} score={agg.get('score')}"
    )
    for scan in report["scans"]:
        print(
            f"{scan.get('symbol', '-'):<5} status={scan.get('status', '-'):<12} "
            f"ratio={scan.get('rv_iv_ratio', '-')} bias={scan.get('bias', '-')}"
        )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(day=args.date)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"RV/IV regime logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
