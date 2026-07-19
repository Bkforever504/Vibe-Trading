#!/usr/bin/env python3
"""Read-only HMM-style market regime scanner.

Uses observable return/volatility features to infer sticky hidden regimes:
trend, chop, and panic. This intentionally avoids adding an hmmlearn dependency;
the model is a small deterministic Gaussian-state approximation with transition
counts for operational context. No orders. No broker calls beyond market data.
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

LOG_PATH = ROOT / "data" / "hmm_regime_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "hmm-regime.json"
SYMBOLS = ["SPY", "QQQ", "IWM"]
LOOKBACK_DAYS = 252
VOL_WINDOW = 10


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _zscore(value: float, values: list[float]) -> float:
    sigma = _std(values)
    return 0.0 if sigma == 0 else (value - _mean(values)) / sigma


def log_returns(closes: list[float]) -> list[float]:
    clean = [float(value) for value in closes if value and float(value) > 0]
    return [math.log(clean[i] / clean[i - 1]) for i in range(1, len(clean))]


def rolling_volatility(returns: list[float], window: int = VOL_WINDOW) -> list[float]:
    if len(returns) < window:
        return []
    return [_std(returns[i - window:i]) * math.sqrt(252) for i in range(window, len(returns) + 1)]


def classify_observation(ret_z: float, vol_z: float) -> str:
    if vol_z >= 1.25 and ret_z <= -0.35:
        return "panic"
    if abs(ret_z) <= 0.45 and vol_z <= 0.5:
        return "chop"
    return "trend"


def transition_matrix(states: list[str]) -> dict[str, dict[str, float]]:
    labels = ["trend", "chop", "panic"]
    counts = {src: {dst: 0 for dst in labels} for src in labels}
    for src, dst in zip(states, states[1:]):
        if src in counts and dst in counts[src]:
            counts[src][dst] += 1
    matrix: dict[str, dict[str, float]] = {}
    for src, row in counts.items():
        total = sum(row.values())
        matrix[src] = {dst: round(count / total, 3) if total else 0.0 for dst, count in row.items()}
    return matrix


def state_probabilities(states: list[str], window: int = 20) -> dict[str, float]:
    labels = ["trend", "chop", "panic"]
    recent = states[-window:] if states else []
    total = len(recent)
    if not total:
        return {label: 0.0 for label in labels}
    return {label: round(recent.count(label) / total, 3) for label in labels}


def scan_symbol(symbol: str, *, day: str) -> dict[str, Any]:
    try:
        from scripts import market_data

        df = market_data.fetch_ohlcv(symbol, lookback_days=LOOKBACK_DAYS + 60)
        closes = [float(value) for value in df["close"].dropna().tolist()]
        data_source = market_data.data_source()
    except Exception as exc:
        return {
            "symbol": symbol,
            "date": day,
            "status": "error",
            "error": str(exc)[:180],
            "state": "unavailable",
            "probabilities": {"trend": 0.0, "chop": 0.0, "panic": 0.0},
        }
    returns = log_returns(closes[-LOOKBACK_DAYS:])
    vols = rolling_volatility(returns)
    aligned_returns = returns[-len(vols):] if vols else []
    if len(aligned_returns) < 40:
        return {
            "symbol": symbol,
            "date": day,
            "status": "unavailable",
            "data_source": data_source,
            "state": "unavailable",
            "probabilities": {"trend": 0.0, "chop": 0.0, "panic": 0.0},
        }
    states = [
        classify_observation(_zscore(ret, aligned_returns), _zscore(vol, vols))
        for ret, vol in zip(aligned_returns, vols)
    ]
    probs = state_probabilities(states)
    state = max(probs, key=probs.get)
    return {
        "symbol": symbol,
        "date": day,
        "status": "ok",
        "data_source": data_source,
        "state": state,
        "probabilities": probs,
        "last_return_z": round(_zscore(aligned_returns[-1], aligned_returns), 3),
        "last_vol_z": round(_zscore(vols[-1], vols), 3),
        "transition_matrix": transition_matrix(states),
    }


def aggregate(scans: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [scan for scan in scans if scan.get("status") == "ok"]
    labels = ["trend", "chop", "panic"]
    if not usable:
        return {"status": "unavailable", "state": "unavailable", "probabilities": {label: 0.0 for label in labels}}
    probs = {
        label: round(sum(float(scan["probabilities"].get(label, 0.0)) for scan in usable) / len(usable), 3)
        for label in labels
    }
    state = max(probs, key=probs.get)
    if probs.get("panic", 0.0) >= 0.35:
        action = "risk_down_context"
    elif state == "trend":
        action = "trend_following_context"
    elif state == "chop":
        action = "mean_reversion_or_wait_context"
    else:
        action = "confirm_with_other_regime_tools"
    return {
        "status": "ok",
        "state": state,
        "probabilities": probs,
        "action_context": action,
        "ok_symbols": len(usable),
    }


def build_report(day: str | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    symbols = symbols or SYMBOLS
    scans = [scan_symbol(symbol, day=day) for symbol in symbols]
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "hmm_regime_scanner",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "aggregate": aggregate(scans),
        "scans": scans,
        "warnings": [
            "Context only. No orders are placed.",
            "HMM-style state is a regime classifier, not a price forecast.",
            "Requires 30 trading days of forward logs before gate discussion.",
        ],
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    agg = report["aggregate"]
    print("\nHMM Regime Scanner | read-only")
    print("=" * 72)
    print(f"{report['date']} state={agg.get('state')} probs={agg.get('probabilities')} action={agg.get('action_context')}")
    for scan in report["scans"]:
        print(f"{scan.get('symbol'):<5} status={scan.get('status'):<12} state={scan.get('state')} probs={scan.get('probabilities')}")
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
        print(f"HMM regime logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
