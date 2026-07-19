#!/usr/bin/env python3
"""Read-only Hurst exponent regime scanner.

Inspired by the Ernie Chan research workflow: estimate whether recent price
action is behaving more like trend persistence, mean reversion, or a random
walk. This is strategy-family context only. It never places orders and must not
become an execution gate without the normal 30-day / 10-sample promotion review.
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
LOG_PATH = ROOT / "data" / "hurst_regime_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "hurst-regime.json"

SYMBOLS = ["SPY", "QQQ", "IWM"]
LOOKBACK_DAYS = 126
MIN_POINTS = 80
MIN_LAG = 2
MAX_LAG = 20
TREND_THRESHOLD = 0.55
MEAN_REVERSION_THRESHOLD = 0.45


def _linear_regression_slope(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom


def hurst_exponent(closes: list[float], min_lag: int = MIN_LAG, max_lag: int = MAX_LAG) -> float | None:
    """Estimate H using log(std(price[t+lag]-price[t])) vs log(lag)."""
    values = [float(value) for value in closes if value is not None and float(value) > 0]
    if len(values) < max(MIN_POINTS, max_lag + 2):
        return None
    log_lags: list[float] = []
    log_tau: list[float] = []
    for lag in range(min_lag, max_lag + 1):
        diffs = [values[i + lag] - values[i] for i in range(len(values) - lag)]
        if len(diffs) < 2:
            continue
        mean = sum(diffs) / len(diffs)
        variance = sum((diff - mean) ** 2 for diff in diffs) / (len(diffs) - 1)
        tau = math.sqrt(variance)
        if tau <= 0:
            continue
        log_lags.append(math.log(lag))
        log_tau.append(math.log(tau))
    slope = _linear_regression_slope(log_lags, log_tau)
    if slope is None:
        return None
    return max(0.0, min(1.0, slope))


def classify_hurst(value: float | None) -> tuple[str, str, float]:
    if value is None:
        return "unavailable", "no_context", 0.0
    if value >= TREND_THRESHOLD:
        return "persistent_trend", "momentum_trend_family", 1.0
    if value <= MEAN_REVERSION_THRESHOLD:
        return "anti_persistent", "mean_reversion_family", -1.0
    return "random_walk_zone", "stand_aside_or_confirm", 0.0


def scan_symbol(symbol: str, *, day: str) -> dict[str, Any]:
    try:
        from scripts import market_data

        df = market_data.fetch_ohlcv(symbol, lookback_days=LOOKBACK_DAYS + 30)
        closes = [float(value) for value in df["close"].dropna().tolist()]
        data_source = market_data.data_source()
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "error",
            "error": str(exc)[:180],
            "regime": "unavailable",
            "bias": "no_context",
            "score": 0.0,
            "date": day,
        }
    hurst = hurst_exponent(closes[-LOOKBACK_DAYS:])
    regime, bias, score = classify_hurst(hurst)
    return {
        "symbol": symbol,
        "status": "ok" if hurst is not None else "unavailable",
        "data_source": data_source,
        "lookback_days": LOOKBACK_DAYS,
        "hurst": round(hurst, 3) if hurst is not None else None,
        "regime": regime,
        "bias": bias,
        "score": score,
        "date": day,
    }


def aggregate(scans: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        scan for scan in scans
        if scan.get("status") == "ok" and isinstance(scan.get("hurst"), int | float)
    ]
    if not usable:
        return {
            "status": "unavailable",
            "regime": "unavailable",
            "bias": "no_context",
            "avg_hurst": None,
            "score": 0.0,
            "votes": {},
            "ok_symbols": 0,
        }
    avg_hurst = sum(float(scan["hurst"]) for scan in usable) / len(usable)
    votes: dict[str, int] = {}
    for scan in usable:
        votes[str(scan.get("bias"))] = votes.get(str(scan.get("bias")), 0) + 1
    vote_bias = max(votes, key=votes.get)
    regime, ratio_bias, score = classify_hurst(avg_hurst)
    if votes.get(vote_bias, 0) >= 2:
        if vote_bias == "momentum_trend_family":
            regime, score = "persistent_trend", 1.0
        elif vote_bias == "mean_reversion_family":
            regime, score = "anti_persistent", -1.0
        elif vote_bias == "stand_aside_or_confirm":
            regime, score = "random_walk_zone", 0.0
        bias = vote_bias
    else:
        bias = ratio_bias
    return {
        "status": "ok",
        "regime": regime,
        "bias": bias,
        "avg_hurst": round(avg_hurst, 3),
        "score": score,
        "votes": votes,
        "ok_symbols": len(usable),
    }


def build_report(day: str | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    symbols = symbols or SYMBOLS
    scans = [scan_symbol(symbol, day=day) for symbol in symbols]
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "hurst_regime",
        "mode": "read_only",
        "execution_enabled": False,
        "thresholds": {
            "momentum_trend_family": TREND_THRESHOLD,
            "mean_reversion_family": MEAN_REVERSION_THRESHOLD,
        },
        "aggregate": aggregate(scans),
        "scans": scans,
        "warnings": [
            "Context only. No orders are placed.",
            "Hurst labels strategy family, not bullish/bearish direction.",
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
    print("\nHurst Regime Scanner | read-only")
    print("=" * 72)
    print(
        f"{report['date']} regime={agg.get('regime')} bias={agg.get('bias')} "
        f"avg_hurst={agg.get('avg_hurst')} score={agg.get('score')}"
    )
    for scan in report["scans"]:
        print(
            f"{scan.get('symbol', '-'):<5} status={scan.get('status', '-'):<12} "
            f"hurst={scan.get('hurst', '-')} bias={scan.get('bias', '-')}"
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
        print(f"Hurst regime logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
