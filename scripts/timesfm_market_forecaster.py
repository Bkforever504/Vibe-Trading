#!/usr/bin/env python3
"""Read-only TimesFM forecast and uncertainty adapter.

TimesFM is a general-purpose time-series foundation model. This adapter records
point-in-time forecasts for later calibration; it never submits orders, changes
position sizing, or participates in a production gate.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "timesfm-market-forecast.json"
LOG_PATH = ROOT / "data" / "timesfm_market_forecast_log.jsonl"
DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "TSLA", "AAPL", "NVDA", "PLTR", "META"]
DEFAULT_MODEL = "google/timesfm-2.5-200m-pytorch"

Fetcher = Callable[[str, str, str], pd.DataFrame]
Predictor = Callable[[str, pd.DataFrame, int], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
        return parsed if pd.notna(parsed) else default
    except (TypeError, ValueError):
        return default


def _float_list(values: Any) -> list[float]:
    if values is None:
        return []
    result: list[float] = []
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            result.append(parsed)
    return result


def fetch_recent_bars(symbol: str, period: str = "60d", interval: str = "15m") -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True).tail(1024)
    except Exception:
        return pd.DataFrame()


def _close_series(bars: pd.DataFrame) -> list[float]:
    for column in ("Close", "close"):
        if column in bars.columns:
            values = pd.to_numeric(bars[column], errors="coerce").dropna().tolist()
            return [float(value) for value in values]
    raise ValueError("bars must contain a Close column")


def load_timesfm_predictor(
    *,
    model_name: str = DEFAULT_MODEL,
    max_context: int = 1024,
    max_horizon: int = 256,
) -> Predictor:
    """Load TimesFM lazily so the production environment has no hard dependency."""
    try:
        import numpy as np
        import timesfm
    except ImportError as exc:
        raise RuntimeError("timesfm_not_installed") from exc

    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(model_name)
    model.compile(
        timesfm.ForecastConfig(
            max_context=max_context,
            max_horizon=max_horizon,
            normalize_inputs=True,
            use_continuous_quantile_head=True,
            force_flip_invariance=True,
            infer_is_positive=True,
            fix_quantile_crossing=True,
        )
    )

    def _predict(symbol: str, bars: pd.DataFrame, pred_len: int) -> dict[str, Any]:
        del symbol
        closes = np.asarray(_close_series(bars), dtype=np.float32)
        point, quantiles = model.forecast(horizon=pred_len, inputs=[closes])
        # TimesFM 2.5 returns mean at index 0, followed by q10 through q90.
        return {
            "point": point[0].tolist(),
            "q10": quantiles[0, :, 1].tolist(),
            "q50": quantiles[0, :, 5].tolist(),
            "q90": quantiles[0, :, 9].tolist(),
        }

    return _predict


def interpret_forecast(
    symbol: str,
    *,
    current_close: float,
    forecast: dict[str, Any],
    model_name: str,
) -> dict[str, Any]:
    point = _float_list(forecast.get("point"))
    q10 = _float_list(forecast.get("q10"))
    q50 = _float_list(forecast.get("q50"))
    q90 = _float_list(forecast.get("q90"))
    if current_close <= 0 or not point or not q10 or not q50 or not q90:
        return _unavailable_row(symbol, "timesfm_incomplete_forecast")

    final_point = point[-1]
    final_q10 = q10[-1]
    final_q50 = q50[-1]
    final_q90 = q90[-1]
    if final_q10 > final_q90:
        return _unavailable_row(symbol, "timesfm_quantile_crossing")

    point_return = ((final_point - current_close) / current_close) * 100.0
    q10_return = ((final_q10 - current_close) / current_close) * 100.0
    q50_return = ((final_q50 - current_close) / current_close) * 100.0
    q90_return = ((final_q90 - current_close) / current_close) * 100.0
    interval_width = ((final_q90 - final_q10) / current_close) * 100.0

    if final_q10 > current_close:
        direction = "bullish_range"
    elif final_q90 < current_close:
        direction = "bearish_range"
    else:
        direction = "uncertain"

    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "model": model_name,
        "forecast_direction": direction,
        "current_close": round(current_close, 4),
        "point_forecast_close": round(final_point, 4),
        "point_forecast_return_pct": round(point_return, 4),
        "q10_close": round(final_q10, 4),
        "q50_close": round(final_q50, 4),
        "q90_close": round(final_q90, 4),
        "q10_return_pct": round(q10_return, 4),
        "q50_return_pct": round(q50_return, 4),
        "q90_return_pct": round(q90_return, 4),
        "q10_q90_width_pct": round(interval_width, 4),
        "quantile_contract": "mean_then_q10_through_q90",
        "calibration_status": "unvalidated",
        "recommended_use": "shadow_uncertainty_context",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_sizing": False,
        "blockers": [
            "timesfm_forward_calibration_required",
            "fewer_than_30_trading_days_of_resolved_forecasts",
        ],
    }


def _unavailable_row(symbol: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "status": "model_unavailable",
        "forecast_direction": "unknown",
        "point_forecast_return_pct": None,
        "calibration_status": "unvalidated",
        "recommended_use": "setup_required",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_sizing": False,
        "blockers": [reason],
    }


def analyze_symbol(
    symbol: str,
    *,
    fetcher: Fetcher,
    predictor: Predictor | None,
    pred_len: int,
    period: str,
    interval: str,
    model_name: str,
) -> dict[str, Any]:
    if predictor is None:
        return _unavailable_row(symbol, "timesfm_not_configured")
    bars = fetcher(symbol, period, interval)
    if bars is None or len(bars) < 2:
        return _unavailable_row(symbol, "timesfm_insufficient_bars")
    try:
        current_close = _close_series(bars)[-1]
        forecast = predictor(symbol, bars, pred_len)
        return interpret_forecast(
            symbol,
            current_close=current_close,
            forecast=forecast,
            model_name=model_name,
        )
    except Exception as exc:
        row = _unavailable_row(symbol, "timesfm_inference_failed")
        row["error"] = str(exc)[:240]
        return row


def build_report(
    symbols: list[str] | None = None,
    *,
    fetcher: Fetcher = fetch_recent_bars,
    predictor: Predictor | None = None,
    load_model: bool = False,
    model_name: str = DEFAULT_MODEL,
    max_context: int = 1024,
    max_horizon: int = 256,
    pred_len: int = 8,
    period: str = "60d",
    interval: str = "15m",
) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    load_error = ""
    if predictor is None and load_model:
        try:
            predictor = load_timesfm_predictor(
                model_name=model_name,
                max_context=max_context,
                max_horizon=max_horizon,
            )
        except Exception as exc:
            load_error = str(exc)[:240]

    items = [
        analyze_symbol(
            symbol,
            fetcher=fetcher,
            predictor=predictor,
            pred_len=pred_len,
            period=period,
            interval=interval,
            model_name=model_name,
        )
        for symbol in symbols
    ]
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "generated_at": _utc_now(),
        "provider": "timesfm_market_forecaster",
        "mode": "read_only_shadow",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_sizing": False,
        "model": model_name,
        "pred_len": pred_len,
        "interval": interval,
        "quantile_contract": "mean_then_q10_through_q90",
        "calibration_status": "unvalidated",
        "summary": {
            "ok": sum(row.get("status") == "ok" for row in items),
            "bullish_range": sum(row.get("forecast_direction") == "bullish_range" for row in items),
            "bearish_range": sum(row.get("forecast_direction") == "bearish_range" for row in items),
            "uncertain": sum(row.get("forecast_direction") == "uncertain" for row in items),
            "unavailable": sum(row.get("status") != "ok" for row in items),
        },
        "items": items,
        "warnings": [
            "Read-only TimesFM adapter. No broker calls, orders, sizing, or production gate authority.",
            "Model quantiles are not calibrated market probabilities.",
            "Promotion requires point-in-time comparison against naive and Kronos baselines.",
        ] + ([f"TimesFM load failed: {load_error}"] if load_error else []),
        "source": {
            "repo": "https://github.com/google-research/timesfm",
            "model": model_name,
        },
    }


def write_report(
    report: dict[str, Any],
    report_path: Path = REPORT_PATH,
    log_path: Path = LOG_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only TimesFM forecast context.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--load-model", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--pred-len", type=int, default=8)
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--max-context", type=int, default=1024)
    parser.add_argument("--max-horizon", type=int, default=256)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()

    report = build_report(
        symbols=args.symbols,
        load_model=args.load_model,
        model_name=args.model,
        pred_len=args.pred_len,
        period=args.period,
        interval=args.interval,
        max_context=args.max_context,
        max_horizon=args.max_horizon,
    )
    write_report(report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
