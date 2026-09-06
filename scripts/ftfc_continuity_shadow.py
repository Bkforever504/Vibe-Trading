#!/usr/bin/env python3
"""Strict bullish FTFC continuity screen reconstructed from the supplied filters.

This is a coverage-priority context lane, not an entry signal. The screenshot
only evidenced the bullish formulation, so no inverse bearish rule is invented.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.daily_stock_screener import SCREENER_UNIVERSE, completed_bars, _rsi14
from scripts.market_data import fetch_ohlcv
from scripts.premarket_opportunity_radar import _atomic_json

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "ftfc-continuity-shadow.json"
MIN_HISTORY = 260


def assess_symbol(symbol: str, frame: pd.DataFrame) -> dict[str, Any]:
    frame = frame.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    required = {"open", "high", "low", "close", "volume"}
    if len(frame) < MIN_HISTORY or not required.issubset(frame.columns):
        return {"symbol": symbol, "status": "blocked", "eligible": False, "blockers": ["insufficient_completed_daily_history"]}
    daily = frame.tail(MIN_HISTORY)
    close, volume = daily.close.astype(float), daily.volume.astype(float)
    monthly = daily.resample("MS").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    weekly = daily.resample("W-FRI").agg({"close": "last"}).dropna()
    last, prior = daily.iloc[-1], daily.iloc[-2]
    pivot = (float(last.high) + float(last.low) + float(last.close)) / 3.0
    daily_rsi, prior_rsi = _rsi14(close), _rsi14(close.iloc[:-1])
    month_rsi, prior_month_rsi = _rsi14(monthly.close), _rsi14(monthly.close.iloc[:-1])
    daily_sma9, daily_ema45 = float(close.rolling(9).mean().iloc[-1]), float(close.ewm(span=45, adjust=False).mean().iloc[-1])
    weekly_sma9, weekly_ema45 = float(weekly.close.rolling(9).mean().iloc[-1]), float(weekly.close.ewm(span=45, adjust=False).mean().iloc[-1])
    month, prior_month = monthly.iloc[-1], monthly.iloc[-2]
    checks = {
        "price_floor_100": float(last.close) >= 100.0,
        "daily_close_above_pivot": float(last.close) > pivot,
        "daily_low_higher_than_prior": float(last.low) > float(prior.low),
        "daily_close_higher_than_prior": float(last.close) > float(prior.close),
        "monthly_close_higher_than_prior": float(month.close) > float(prior_month.close),
        "daily_green": float(last.close) > float(last.open),
        "monthly_green": float(month.close) > float(month.open),
        "daily_change_ge_1_5pct": float(last.close / prior.close - 1.0) >= 0.015,
        "daily_volume_above_sma9": float(volume.iloc[-1]) > float(volume.rolling(9).mean().iloc[-1]),
        "daily_volume_ge_1m": float(volume.iloc[-1]) >= 1_000_000,
        "daily_rsi_rising_below_70": daily_rsi > prior_rsi and daily_rsi < 70.0,
        "monthly_rsi_rising": month_rsi > prior_month_rsi,
        "daily_sma9_above_ema45": daily_sma9 > daily_ema45,
        "weekly_sma9_above_ema45": weekly_sma9 > weekly_ema45,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {"symbol": symbol, "status": "ftfc_bullish_continuity" if not blockers else "watch", "eligible": not blockers, "score": round(100.0 * sum(checks.values()) / len(checks), 1), "checks": checks, "blockers": blockers, "metrics": {"price": round(float(last.close), 4), "daily_rsi14": round(daily_rsi, 2), "monthly_rsi14": round(month_rsi, 2), "daily_volume": round(float(volume.iloc[-1])), "pivot": round(pivot, 4)}, "authority": "coverage_priority_only_no_rank_entry_alert_or_execution", "execution_enabled": False, "can_submit_orders": False}


def build_report(symbols: tuple[str, ...] = SCREENER_UNIVERSE, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now().date()
    rows, errors = [], {}
    for symbol in symbols:
        try:
            rows.append(assess_symbol(symbol, completed_bars(fetch_ohlcv(symbol, lookback_days=900), as_of)))
        except Exception as exc:
            errors[symbol] = type(exc).__name__
    eligible = [row for row in rows if row.get("eligible")]
    return {"schema_version": 1, "date": as_of.isoformat(), "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "mode": "shadow_context", "source": "user_supplied_FTFC_bullish_filter_screenshot", "scope": "bullish_only_bearish_inverse_not_evidenced", "rankings": sorted(eligible, key=lambda row: float(row["score"]), reverse=True), "observations": rows, "coverage": {"requested": len(symbols), "eligible": len(eligible), "errors": len(errors)}, "errors": errors, "execution_enabled": False, "can_submit_orders": False, "warning": "FTFC continuity prioritizes coverage only. A candidate still requires independent catalyst, tradeability, same-time RVOL, and completed-bar entry evidence."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report()
    _atomic_json(args.report_path, report)
    print(f"FTFC continuity: eligible={report['coverage']['eligible']} requested={report['coverage']['requested']} errors={report['coverage']['errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
