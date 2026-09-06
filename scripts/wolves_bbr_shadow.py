#!/usr/bin/env python3
"""Read-only Wolves/BBR level-and-EMA observation lane.

This is deliberately an attribution report, not a strategy or an order source.
It maps completed prior-day and current premarket levels, then checks completed
5-minute bars for the source-matched 200/8/13/48 EMA and break/hold context.
It never changes the intraday radar rank, a grade, sizing, or execution.
"""
from __future__ import annotations

import argparse
import json
import sys
import time as time_module
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import CORE_LIQUID_SYMBOLS, MARKET_TZ, _credentials, _finite, _read_json
from scripts.premarket_opportunity_radar import _atomic_json

VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "wolves-bbr-shadow.json"
BAR_URL = "https://data.alpaca.markets/v2/stocks/bars"
MAX_SYMBOLS = 80
MIN_BBR_AVG_DOLLAR_VOLUME = 100_000_000
ALPACA_RETRY_ATTEMPTS = 3


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MARKET_TZ)


def _fetch_page(
    params: dict[str, Any], *, requester: Any = requests.get,
    sleeper: Any = time_module.sleep, attempts: int = ALPACA_RETRY_ATTEMPTS,
) -> dict[str, Any]:
    """Retry transient Alpaca failures; never turn a failed page into data."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requester(BAR_URL, headers=_credentials(), params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Alpaca bars response is not an object")
            return payload
        except Exception as exc:  # surfaced after bounded retry; no data fallback
            last_error = exc
            if attempt < attempts:
                sleeper(0.35 * attempt)
    assert last_error is not None
    raise last_error


def _fetch_bars(symbols: list[str], now_et: datetime) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    if not symbols:
        return {}, []
    completed = now_et.replace(minute=now_et.minute - now_et.minute % 5, second=0, microsecond=0)
    start = datetime.combine(now_et.date() - timedelta(days=16), time(4), MARKET_TZ)
    output: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    # A 16-day 5m history easily exceeds the provider's page cap for a
    # 100-symbol request.  Small batches preserve complete histories for the
    # liquid core instead of silently returning the alphabetically early rows.
    for offset in range(0, len(symbols), 16):
        params: dict[str, Any] = {
            "symbols": ",".join(symbols[offset:offset + 16]), "timeframe": "5Min",
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": completed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "adjustment": "raw", "feed": "iex", "limit": 10000, "sort": "asc",
        }
        token = None
        for _ in range(4):
            if token:
                params["page_token"] = token
            else:
                params.pop("page_token", None)
            try:
                payload = _fetch_page(params)
            except Exception as exc:
                errors.append(f"alpaca_bbr_bars:{type(exc).__name__}")
                break
            for symbol, rows in (payload.get("bars") or {}).items():
                output.setdefault(str(symbol).upper(), []).extend(row for row in rows or [] if isinstance(row, dict))
            token = payload.get("next_page_token")
            if not token:
                break
    return output, errors


def assess_symbol(symbol: str, rows: list[dict[str, Any]], now_et: datetime) -> dict[str, Any]:
    parsed = []
    for row in rows:
        stamp = _parse_time(row.get("t"))
        values = {key: _finite(row.get(key)) for key in ("o", "h", "l", "c", "v")}
        if stamp and all(value is not None for value in values.values()):
            parsed.append({"dt": stamp, **values})
    if not parsed:
        return {"symbol": symbol, "status": "unavailable", "reason": "no_completed_bars"}
    frame = pd.DataFrame(parsed).sort_values("dt").drop_duplicates("dt")
    rth = frame[(frame.dt.dt.time >= time(9, 30)) & (frame.dt.dt.time < time(16))].copy()
    if len(rth) < 205:
        return {"symbol": symbol, "status": "unavailable", "reason": "insufficient_rth_history", "rth_bars": len(rth)}
    rth["date"] = rth.dt.dt.date
    dates = sorted(rth.date.unique())
    today = now_et.date()
    previous = [day for day in dates if day < today]
    if not previous or today not in dates:
        return {"symbol": symbol, "status": "unavailable", "reason": "prior_or_current_session_missing"}
    prior_day = previous[-1]
    prior = rth[rth.date == prior_day]
    current = rth[rth.date == today].copy()
    if len(current) < 2:
        return {"symbol": symbol, "status": "unavailable", "reason": "current_session_too_short"}
    premarket = frame[(frame.dt.dt.date == today) & (frame.dt.dt.time >= time(4)) & (frame.dt.dt.time < time(9, 30))]
    current["ema8"] = rth.c.ewm(span=8, adjust=False).mean().tail(len(current)).to_numpy()
    current["ema13"] = rth.c.ewm(span=13, adjust=False).mean().tail(len(current)).to_numpy()
    current["ema48"] = rth.c.ewm(span=48, adjust=False).mean().tail(len(current)).to_numpy()
    current["ema200"] = rth.c.ewm(span=200, adjust=False).mean().tail(len(current)).to_numpy()
    last, prior_bar = current.iloc[-1], current.iloc[-2]
    levels = {"prior_day_high": float(prior.h.max()), "prior_day_low": float(prior.l.min())}
    if premarket.empty:
        return {"symbol": symbol, "status": "levels_incomplete", "levels": levels, "reason": "premarket_data_unavailable", "execution_enabled": False, "can_submit_orders": False}
    levels.update({"premarket_high": float(premarket.h.max()), "premarket_low": float(premarket.l.min())})
    long_level, short_level = max(levels["prior_day_high"], levels["premarket_high"]), min(levels["prior_day_low"], levels["premarket_low"])
    close, prior_close = float(last.c), float(prior_bar.c)
    bull_ema = close > float(last.ema200) and float(last.ema8) > float(last.ema13) > float(last.ema48)
    bear_ema = close < float(last.ema200) and float(last.ema8) < float(last.ema13) < float(last.ema48)
    tolerance = max(long_level - short_level, close * 0.002) * 0.08
    prior_window = current.iloc[max(0, len(current) - 7):-1]
    long_break = prior_close <= long_level and close > long_level
    short_break = prior_close >= short_level and close < short_level
    long_hold = bool((prior_window.c > long_level).any() and float(last.l) <= long_level + tolerance and close > long_level)
    short_hold = bool((prior_window.c < short_level).any() and float(last.h) >= short_level - tolerance and close < short_level)
    direction = "bullish" if bull_ema and (long_break or long_hold) else "bearish" if bear_ema and (short_break or short_hold) else "none"
    behavior = "break" if (long_break or short_break) else "hold_retest" if (long_hold or short_hold) else "none"
    return {
        "symbol": symbol, "status": "observed", "direction": direction, "behavior": behavior,
        "source_matched_confluence": direction != "none", "levels": {key: round(value, 4) for key, value in levels.items()},
        "active_long_level": round(long_level, 4), "active_short_level": round(short_level, 4),
        "last_close": round(close, 4), "last_completed_bar_at": last["dt"].isoformat(),
        "ema": {key: round(float(last[key]), 4) for key in ("ema8", "ema13", "ema48", "ema200")},
        "ema_alignment": "bullish_stack" if bull_ema else "bearish_stack" if bear_ema else "not_aligned",
        "definition": "completed_5m_prior_day_and_premarket_level_break_or_hold_with_200_8_13_48_ema_stack",
        "authority": "shadow_attribution_only_no_rank_alert_or_execution_effect", "execution_enabled": False, "can_submit_orders": False,
    }


def build_report(now_et: datetime | None = None, radar_path: Path = RADAR_PATH) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    radar = _read_json(radar_path)
    candidates = radar.get("ranked_candidates") if isinstance(radar.get("ranked_candidates"), list) else []
    # Give the lane a stable liquid core first, then the radar's liquid
    # candidates.  This avoids letting temporary microcap movers consume the
    # source-matched research budget.
    liquid = [
        str(row.get("symbol") or "").upper() for row in candidates if isinstance(row, dict)
        and (_finite(row.get("avg_dollar_volume_20d")) or 0) >= MIN_BBR_AVG_DOLLAR_VOLUME
        and (_finite(row.get("price")) or 0) >= 10.0
    ]
    ranked = [str(row.get("symbol") or "").upper() for row in candidates if isinstance(row, dict)]
    symbols = list(dict.fromkeys([*CORE_LIQUID_SYMBOLS, *liquid, *ranked]))[:MAX_SYMBOLS]
    symbols = [symbol for symbol in symbols if symbol]
    bars, errors = _fetch_bars(symbols, now_et)
    observations = [assess_symbol(symbol, bars.get(symbol, []), now_et) for symbol in symbols]
    hits = [row for row in observations if row.get("source_matched_confluence")]
    by_symbol = {str(row.get("symbol") or ""): row for row in observations}
    core_debts = [
        {"symbol": symbol, "status": (by_symbol.get(symbol) or {}).get("status", "not_requested"), "reason": (by_symbol.get(symbol) or {}).get("reason", "not_requested")}
        for symbol in CORE_LIQUID_SYMBOLS if (by_symbol.get(symbol) or {}).get("status") != "observed"
    ]
    return {"schema_version": 3, "date": now_et.date().isoformat(), "as_of_et": now_et.isoformat(), "mode": "shadow_observation", "execution_enabled": False, "can_submit_orders": False, "source": "Wolves_of_Wealth_BBR_public_rules_partial", "coverage": {"radar_symbols_considered": len(symbols), "liquid_core_requested": list(CORE_LIQUID_SYMBOLS), "bars_received": len(bars), "observations_complete": sum(row.get("status") == "observed" for row in observations), "confluence_hits": len(hits), "liquid_core_coverage_debt_count": len(core_debts), "liquid_core_coverage_debts": core_debts}, "confluence_hits": hits, "observations": observations, "errors": errors, "warning": "This reports source-matched context only. The public material lacks frozen stop, target, retest, and exit semantics; this has no rank, alert, sizing, or execution authority. Missing extended-hours history is a visible coverage debt, not a reason to substitute a weaker source."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="show")
    args = parser.parse_args()
    report = build_report()
    _atomic_json(args.report_path, report)
    if args.show:
        print(json.dumps(report, indent=2))
    else:
        print(f"Wolves BBR shadow: complete={report['coverage']['observations_complete']} hits={report['coverage']['confluence_hits']} errors={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
