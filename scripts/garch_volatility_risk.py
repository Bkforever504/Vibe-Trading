#!/usr/bin/env python3
"""Daily GARCH volatility risk report.

This is a sizing/risk-throttle layer only. It forecasts volatility magnitude,
not trade direction, and never submits orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "garch-volatility-risk.json"
LOG_PATH = ROOT / "data" / "garch_volatility_risk_log.jsonl"

DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "TSLA", "PLTR"]
TRADING_DAYS = 252
MIN_OBS = 510
HONESTY_NOTE = (
    "GARCH forecasts volatility magnitude, not direction. It should size or "
    "throttle risk, never create a buy/sell signal by itself."
)


def size_from_forecast(
    forecast_vol_ann: float | None,
    *,
    target_vol: float = 15.0,
    min_multiplier: float = 0.25,
    max_multiplier: float = 1.0,
) -> float:
    if forecast_vol_ann is None or forecast_vol_ann <= 0 or math.isnan(forecast_vol_ann):
        return min_multiplier
    return float(np.clip(target_vol / forecast_vol_ann, min_multiplier, max_multiplier))


def classify_regime(vol_percentile: float | None) -> str:
    if vol_percentile is None or math.isnan(vol_percentile):
        return "unknown"
    if vol_percentile >= 67:
        return "storm"
    if vol_percentile <= 33:
        return "calm"
    return "normal"


def latest_garch_forecast(close: pd.Series) -> dict[str, Any]:
    from arch import arch_model

    clean = close.dropna().astype(float)
    returns = 100.0 * clean.pct_change().dropna()
    if len(returns) < MIN_OBS:
        raise ValueError(f"need at least {MIN_OBS} daily returns; got {len(returns)}")

    model = arch_model(returns, vol="GARCH", p=1, q=1, mean="Constant", dist="t")
    result = model.fit(disp="off", show_warning=False)
    forecast = result.forecast(horizon=1, reindex=False)
    daily_vol_pct = float(np.sqrt(forecast.variance.iloc[-1, 0]))
    ann_vol_pct = daily_vol_pct * math.sqrt(TRADING_DAYS)

    realized_ann_vol = returns.rolling(21).std() * math.sqrt(TRADING_DAYS)
    history = realized_ann_vol.dropna().tail(252)
    vol_percentile = None
    if len(history) >= 90:
        vol_percentile = float((history < ann_vol_pct).mean() * 100.0)

    return {
        "forecast_vol_daily_pct": round(daily_vol_pct, 4),
        "forecast_vol_annualized_pct": round(ann_vol_pct, 2),
        "vol_percentile_1y": round(vol_percentile, 2) if vol_percentile is not None else None,
        "fit_observations": int(len(returns)),
    }


def scan_symbol(
    symbol: str,
    *,
    target_vol: float,
    min_multiplier: float,
    max_multiplier: float,
    lookback_days: int,
) -> dict[str, Any]:
    try:
        from scripts import market_data

        df = market_data.fetch_ohlcv(symbol, lookback_days=lookback_days)
        forecast = latest_garch_forecast(df["close"])
        multiplier = size_from_forecast(
            float(forecast["forecast_vol_annualized_pct"]),
            target_vol=target_vol,
            min_multiplier=min_multiplier,
            max_multiplier=max_multiplier,
        )
        regime = classify_regime(forecast.get("vol_percentile_1y"))
        return {
            "symbol": symbol,
            "status": "ok",
            "data_source": market_data.data_source(),
            **forecast,
            "target_vol_pct": target_vol,
            "position_size_multiplier": round(multiplier, 3),
            "regime": regime,
            "risk_posture": "block_new_entries" if regime == "storm" else "scale_size",
        }
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "error",
            "error": str(exc)[:220],
            "position_size_multiplier": min_multiplier,
            "regime": "unknown",
            "risk_posture": "report_unavailable",
        }


def build_report(
    *,
    symbols: list[str] | None = None,
    target_vol: float = 15.0,
    min_multiplier: float = 0.25,
    max_multiplier: float = 1.0,
    lookback_days: int = 900,
) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    scans = [
        scan_symbol(
            symbol,
            target_vol=target_vol,
            min_multiplier=min_multiplier,
            max_multiplier=max_multiplier,
            lookback_days=lookback_days,
        )
        for symbol in symbols
    ]
    ok = [row for row in scans if row.get("status") == "ok"]
    storm = [row["symbol"] for row in ok if row.get("regime") == "storm"]
    min_mult = min((float(row.get("position_size_multiplier") or 1.0) for row in ok), default=None)
    return {
        "date": date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "provider": "garch_volatility_risk",
        "mode": "read_only_risk_sizing",
        "execution_enabled": False,
        "symbols": scans,
        "summary": {
            "ok_symbols": len(ok),
            "storm_symbols": storm,
            "minimum_position_size_multiplier": round(min_mult, 3) if min_mult is not None else None,
        },
        "parameters": {
            "target_vol_pct": target_vol,
            "min_multiplier": min_multiplier,
            "max_multiplier": max_multiplier,
            "lookback_days": lookback_days,
            "trading_days": TRADING_DAYS,
        },
        "note": HONESTY_NOTE,
        "warnings": [
            "No orders are placed.",
            "This report forecasts volatility magnitude only.",
            "For options automation, storm regimes should reduce or block new risk unless separately approved.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}")
    try:
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)
        return path
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        fallback = path.with_name(f"{path.stem}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{path.suffix}")
        report.setdefault("warnings", []).append(f"Primary report path was unavailable; wrote fallback {fallback}")
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        try:
            fallback.write_text(payload, encoding="utf-8")
            return fallback
        except OSError:
            return path


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nGARCH Volatility Risk | read-only")
    print("=" * 72)
    print(
        f"{report['date']} ok={report['summary']['ok_symbols']} "
        f"storm={','.join(report['summary']['storm_symbols']) or '-'} "
        f"min_mult={report['summary']['minimum_position_size_multiplier']}"
    )
    for row in report["symbols"]:
        print(
            f"{row['symbol']:<5} status={row['status']:<5} regime={row.get('regime', '-'):<7} "
            f"vol={row.get('forecast_vol_annualized_pct', '-')}% "
            f"mult={row.get('position_size_multiplier', '-')}"
        )
    print("No orders placed. GARCH forecasts magnitude, not direction.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--target-vol", type=float, default=15.0)
    parser.add_argument("--min-multiplier", type=float, default=0.25)
    parser.add_argument("--max-multiplier", type=float, default=1.0)
    parser.add_argument("--lookback-days", type=int, default=900)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args(argv)

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    report = build_report(
        symbols=symbols,
        target_vol=args.target_vol,
        min_multiplier=args.min_multiplier,
        max_multiplier=args.max_multiplier,
        lookback_days=args.lookback_days,
    )
    if not args.no_write:
        write_report(report)
        append_log(report)
    if args.print:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
