#!/usr/bin/env python3
"""Read-only candlestick and price-action context scanner.

This translates classic candlestick/price-action concepts into original,
testable features. It does not place orders, call broker endpoints, or change
bot settings.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "candlestick-context.json"
LOG_PATH = ROOT / "data" / "candlestick_context_log.jsonl"
DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "TSLA", "AAPL", "NVDA", "PLTR", "META"]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if pd.notna(parsed) else default
    except (TypeError, ValueError):
        return default


def fetch_recent_bars(symbol: str, period: str = "5d", interval: str = "15m") -> pd.DataFrame:
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
        return df.tail(80).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _candle_parts(row: pd.Series) -> dict[str, float]:
    open_ = _safe_float(row.get("Open"))
    high = _safe_float(row.get("High"))
    low = _safe_float(row.get("Low"))
    close = _safe_float(row.get("Close"))
    body = abs(close - open_)
    candle_range = max(high - low, 0.0001)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "body": body,
        "range": candle_range,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "bullish": close > open_,
        "bearish": close < open_,
    }


def analyze_symbol(symbol: str, bars: pd.DataFrame, reference_levels: dict[str, float] | None = None) -> dict[str, Any]:
    reference_levels = reference_levels or {}
    if bars is None or len(bars) < 2:
        return {
            "symbol": symbol,
            "status": "no_data",
            "bias": "neutral",
            "primary_signal": "none",
            "features": [],
            "allowed_playbooks": ["stand_aside", "needs_review"],
            "veto_reasons": ["insufficient_candles"],
        }

    prev = _candle_parts(bars.iloc[-2])
    cur = _candle_parts(bars.iloc[-1])
    features: list[str] = []
    vetoes: list[str] = []
    primary = "none"
    bias = "neutral"

    prev_body_low = min(prev["open"], prev["close"])
    prev_body_high = max(prev["open"], prev["close"])
    cur_body_low = min(cur["open"], cur["close"])
    cur_body_high = max(cur["open"], cur["close"])
    avg_volume = _safe_float(bars["Volume"].tail(min(len(bars), 20)).mean(), 0.0) if "Volume" in bars else 0.0
    cur_volume = _safe_float(bars.iloc[-1].get("Volume"))
    volume_expansion = cur_volume > avg_volume * 1.2 if avg_volume > 0 else False

    vwap = _safe_float(reference_levels.get("vwap"))
    prior_high = _safe_float(reference_levels.get("prior_high"))
    prior_low = _safe_float(reference_levels.get("prior_low"))

    bullish_engulfing = (
        prev["bearish"]
        and cur["bullish"]
        and cur_body_low <= prev_body_low
        and cur_body_high >= prev_body_high
    )
    bearish_engulfing = (
        prev["bullish"]
        and cur["bearish"]
        and cur_body_high >= prev_body_high
        and cur_body_low <= prev_body_low
    )
    reclaimed_vwap = bool(vwap and prev["close"] < vwap <= cur["close"])
    failed_breakout = bool(prior_high and cur["high"] >= prior_high and cur["close"] < prior_high)
    lower_wick_ratio = cur["lower_wick"] / cur["range"]
    support_sweep = bool(prior_low and cur["low"] <= prior_low and cur["close"] > prior_low)

    if bullish_engulfing and (reclaimed_vwap or volume_expansion):
        primary = "bullish_engulfing_reclaim"
        bias = "bullish"
        features.extend(["bullish_engulfing", "vwap_reclaim" if reclaimed_vwap else "volume_expansion"])
    elif bearish_engulfing and failed_breakout:
        primary = "bearish_engulfing_failed_breakout"
        bias = "bearish"
        features.extend(["bearish_engulfing", "failed_breakout"])
    elif support_sweep and lower_wick_ratio >= 0.45 and cur["bullish"]:
        primary = "bullish_liquidity_grab"
        bias = "bullish"
        features.extend(["support_wick_rejection", "liquidity_sweep"])
    elif cur["body"] / cur["range"] < 0.25:
        primary = "compression_or_indecision"
        vetoes.append("wait_for_expansion_confirmation")

    if bias == "bullish":
        allowed = ["directional_long_call", "bullish_debit_spread", "stand_aside"]
    elif bias == "bearish":
        allowed = ["directional_long_put", "bearish_debit_spread", "stand_aside"]
    else:
        allowed = ["stand_aside", "needs_review"]

    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "bias": bias,
        "primary_signal": primary,
        "features": features,
        "allowed_playbooks": allowed,
        "veto_reasons": vetoes,
        "last_close": round(cur["close"], 4),
        "volume_expansion": volume_expansion,
        "reference_levels": reference_levels,
    }


def build_report(symbols: list[str] | None = None) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    items = [analyze_symbol(symbol, fetch_recent_bars(symbol)) for symbol in symbols]
    summary = dict(Counter(row.get("bias", "neutral") for row in items))
    for key in ["bullish", "bearish", "neutral"]:
        summary.setdefault(key, 0)
    return {
        "provider": "candlestick_context_scanner",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "summary": summary,
        "items": items,
        "warnings": [
            "Read-only context. Candlestick patterns are not trade triggers without higher timeframe and catalyst confirmation.",
            "No broker calls. No orders. No settings changes.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Candlestick context scanner - read-only.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.symbols)
    write_report(report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Candlestick context written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
