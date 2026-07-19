#!/usr/bin/env python3
"""Read-only Kronos forecast adapter.

Kronos is useful as K-line forecast context, not execution authority. This
script can run real Kronos inference when a local Kronos checkout is configured,
and otherwise emits an explicit setup-required report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "kronos-market-forecast.json"
LOG_PATH = ROOT / "data" / "kronos_market_forecast_log.jsonl"
DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "TSLA", "AAPL", "NVDA", "PLTR", "META"]
DEFAULT_MODEL = "NeoQuasar/Kronos-small"
DEFAULT_TOKENIZER = "NeoQuasar/Kronos-Tokenizer-base"
DEFAULT_LOCAL_REPO = ROOT / "research" / "external_repos" / "Kronos"

Fetcher = Callable[[str, str, str], pd.DataFrame]
Predictor = Callable[[str, pd.DataFrame, int], list[float]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if pd.notna(parsed) else default
    except (TypeError, ValueError):
        return default


def fetch_recent_bars(symbol: str, period: str = "5d", interval: str = "15m") -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True).tail(512)
    except Exception:
        return pd.DataFrame()


def _timestamp_series(bars: pd.DataFrame) -> pd.Series:
    if isinstance(bars.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(bars.index))
    for name in ("Datetime", "Date", "timestamp", "timestamps"):
        if name in bars.columns:
            return pd.Series(pd.to_datetime(bars[name]))
    return pd.Series(pd.date_range(end=pd.Timestamp.utcnow(), periods=len(bars), freq="15min"))


def _future_timestamps(x_timestamp: pd.Series, pred_len: int) -> pd.Series:
    if len(x_timestamp) >= 2:
        delta = x_timestamp.iloc[-1] - x_timestamp.iloc[-2]
    else:
        delta = pd.Timedelta(minutes=15)
    if not isinstance(delta, pd.Timedelta) or delta <= pd.Timedelta(0):
        delta = pd.Timedelta(minutes=15)
    start = x_timestamp.iloc[-1] + delta
    return pd.Series([start + delta * i for i in range(pred_len)])


def _to_kronos_frame(bars: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = bars.rename(columns=rename).copy()
    required = ["open", "high", "low", "close"]
    if not all(col in df.columns for col in required):
        raise ValueError("bars must contain OHLC columns")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["amount"] = df.get("amount", df["volume"] * df[required].mean(axis=1))
    return df[["open", "high", "low", "close", "volume", "amount"]].dropna()


def load_kronos_predictor(
    *,
    kronos_repo_path: str | Path,
    model_name: str = DEFAULT_MODEL,
    tokenizer_name: str = DEFAULT_TOKENIZER,
    device: str | None = None,
    max_context: int = 512,
    sample_count: int = 5,
) -> Predictor:
    repo_path = Path(kronos_repo_path).expanduser()
    if not repo_path.exists():
        raise RuntimeError("kronos_not_configured")
    sys.path.insert(0, str(repo_path))
    from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
    model = Kronos.from_pretrained(model_name)
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=max_context)

    def _predict(symbol: str, bars: pd.DataFrame, pred_len: int) -> list[float]:
        import torch

        frame = _to_kronos_frame(bars)
        x_timestamp = _timestamp_series(frame)
        y_timestamp = _future_timestamps(x_timestamp, pred_len)
        seed_material = f"{symbol.upper()}|{x_timestamp.iloc[-1]}|{pred_len}"
        seed = int.from_bytes(hashlib.sha256(seed_material.encode("utf-8")).digest()[:4], "big")
        torch.manual_seed(seed)
        pred_df = predictor.predict(
            df=frame,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=1.0,
            top_p=0.9,
            sample_count=max(1, sample_count),
            verbose=False,
        )
        return [_safe_float(value) for value in pred_df["close"].tolist()]

    return _predict


def default_kronos_repo_path() -> str:
    configured = os.getenv("KRONOS_REPO_PATH", "").strip()
    if configured:
        return configured
    return str(DEFAULT_LOCAL_REPO) if DEFAULT_LOCAL_REPO.exists() else ""


def interpret_forecast(
    symbol: str,
    *,
    current_close: float,
    forecast_closes: list[float],
    model_name: str,
) -> dict[str, Any]:
    if not forecast_closes or current_close <= 0:
        return {
            "symbol": symbol.upper(),
            "status": "no_forecast",
            "recommended_use": "setup_required",
            "can_submit_orders": False,
            "blockers": ["kronos_no_forecast"],
        }
    final_close = _safe_float(forecast_closes[-1])
    forecast_return = ((final_close - current_close) / current_close) * 100.0
    min_close = min(forecast_closes)
    max_close = max(forecast_closes)
    max_drawdown = min(0.0, ((min_close - current_close) / current_close) * 100.0)
    max_runup = max(0.0, ((max_close - current_close) / current_close) * 100.0)
    if forecast_return >= 0.75:
        direction = "bullish"
    elif forecast_return <= -0.75:
        direction = "bearish"
    else:
        direction = "flat"
    confidence = min(1.0, abs(forecast_return) / 3.0)
    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "model": model_name,
        "forecast_direction": direction,
        "current_close": round(current_close, 4),
        "forecast_close": round(final_close, 4),
        "forecast_return_pct": round(forecast_return, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "max_runup_pct": round(max_runup, 2),
        "confidence": round(confidence, 2),
        "recommended_use": "shadow_context",
        "can_submit_orders": False,
        "blockers": ["shadow_not_promotion_ready"],
    }


def _unavailable_row(symbol: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "status": "model_unavailable",
        "forecast_direction": "unknown",
        "forecast_return_pct": None,
        "confidence": 0.0,
        "recommended_use": "setup_required",
        "can_submit_orders": False,
        "blockers": [reason],
    }


def analyze_symbol(
    symbol: str,
    *,
    fetcher: Fetcher = fetch_recent_bars,
    predictor: Predictor | None,
    pred_len: int,
    period: str,
    interval: str,
    model_name: str,
) -> dict[str, Any]:
    if predictor is None:
        return _unavailable_row(symbol, "kronos_not_configured")
    bars = fetcher(symbol, period, interval)
    if bars is None or len(bars) < 2:
        return _unavailable_row(symbol, "kronos_insufficient_bars")
    try:
        forecast_closes = predictor(symbol, bars, pred_len)
        current_close = _safe_float(bars.iloc[-1].get("Close", bars.iloc[-1].get("close")))
        return interpret_forecast(
            symbol,
            current_close=current_close,
            forecast_closes=forecast_closes,
            model_name=model_name,
        )
    except Exception as exc:
        row = _unavailable_row(symbol, "kronos_inference_failed")
        row["error"] = str(exc)[:240]
        return row


def build_report(
    symbols: list[str] | None = None,
    *,
    fetcher: Fetcher = fetch_recent_bars,
    predictor: Predictor | None = None,
    kronos_repo_path: str | Path | None = None,
    model_name: str = DEFAULT_MODEL,
    tokenizer_name: str = DEFAULT_TOKENIZER,
    device: str | None = None,
    max_context: int = 512,
    sample_count: int = 5,
    pred_len: int = 8,
    period: str = "5d",
    interval: str = "15m",
) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    load_error = ""
    if predictor is None and kronos_repo_path:
        try:
            predictor = load_kronos_predictor(
                kronos_repo_path=kronos_repo_path,
                model_name=model_name,
                tokenizer_name=tokenizer_name,
                device=device,
                max_context=max_context,
                sample_count=sample_count,
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
    summary = {
        "ok": sum(1 for row in items if row.get("status") == "ok"),
        "bullish": sum(1 for row in items if row.get("forecast_direction") == "bullish"),
        "bearish": sum(1 for row in items if row.get("forecast_direction") == "bearish"),
        "flat": sum(1 for row in items if row.get("forecast_direction") == "flat"),
        "unavailable": sum(1 for row in items if row.get("status") != "ok"),
    }
    warnings = [
        "Read-only Kronos adapter. No broker calls. No orders. No execution authority.",
        "Forecasts are shadow context only until forward evidence proves value.",
    ]
    if load_error:
        warnings.append(f"Kronos load failed: {load_error}")
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "generated_at": _utc_now(),
        "provider": "kronos_market_forecaster",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "model": model_name,
        "tokenizer": tokenizer_name,
        "pred_len": pred_len,
        "sample_count": sample_count,
        "interval": interval,
        "summary": summary,
        "items": items,
        "warnings": warnings,
        "source": {
            "repo": "https://github.com/shiyu-coder/Kronos",
            "kronos_repo_path": str(kronos_repo_path or default_kronos_repo_path()),
        },
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only Kronos market forecast context.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--kronos-repo-path", default=default_kronos_repo_path())
    parser.add_argument("--model", default=os.getenv("KRONOS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--tokenizer", default=os.getenv("KRONOS_TOKENIZER", DEFAULT_TOKENIZER))
    parser.add_argument("--device", default=os.getenv("KRONOS_DEVICE", None))
    parser.add_argument("--pred-len", type=int, default=int(os.getenv("KRONOS_PRED_LEN", "8")))
    parser.add_argument("--sample-count", type=int, default=int(os.getenv("KRONOS_SAMPLE_COUNT", "5")))
    parser.add_argument("--period", default=os.getenv("KRONOS_PERIOD", "5d"))
    parser.add_argument("--interval", default=os.getenv("KRONOS_INTERVAL", "15m"))
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(
        args.symbols,
        kronos_repo_path=args.kronos_repo_path,
        model_name=args.model,
        tokenizer_name=args.tokenizer,
        device=args.device,
        pred_len=args.pred_len,
        sample_count=args.sample_count,
        period=args.period,
        interval=args.interval,
    )
    write_report(report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Kronos market forecast written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
