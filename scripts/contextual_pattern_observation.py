#!/usr/bin/env python3
"""Observe, but never trade, contextual inside-bar and 4H-to-15m FVG sequences.

The module deliberately treats the screenshot mechanics as unvalidated research
hypotheses.  It captures completed-bar geometry and the context that existed at
observation time; it has no rank, alert, sizing, or broker authority.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

try:
    from scripts.candlestick_context_scanner import fetch_recent_bars
except ModuleNotFoundError:  # allows direct execution from scripts/
    from candlestick_context_scanner import fetch_recent_bars


VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "contextual-pattern-observation.json"
ET = ZoneInfo("America/New_York")
CORE_WATCHLIST = ("SPY", "QQQ", "IWM", "MRNA")
MAX_RADAR_SYMBOLS = 12
GAP_MINIMUM = 0.02
SESSION_EXPANSION_MINIMUM = 0.01
REACTION_ATR_MULTIPLE = 0.50


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if pd.notna(parsed) else None
    except (TypeError, ValueError):
        return None


def _prepared(bars: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """Return completed, ET-indexed 15m OHLCV bars only.

    Provider data may include a forming bar.  Excluding the final interval is
    intentionally conservative and avoids making the current candle visible
    before it has closed.
    """
    required = {"Open", "High", "Low", "Close", "Volume"}
    if bars is None or bars.empty or not required.issubset(bars.columns):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    result = bars.loc[:, ["Open", "High", "Low", "Close", "Volume"]].copy()
    index = pd.to_datetime(result.index, errors="coerce", utc=True)
    result = result.loc[index.notna()].copy()
    result.index = index[index.notna()].tz_convert(ET)
    cutoff = as_of.astimezone(ET) - pd.Timedelta(minutes=15)
    result = result[result.index <= cutoff]
    return result.sort_index()


def inside_bar(bars: pd.DataFrame) -> dict[str, Any]:
    if len(bars) < 2:
        return {"state": "insufficient_completed_15m_bars"}
    mother, current = bars.iloc[-2], bars.iloc[-1]
    observed = bool(float(current["High"]) <= float(mother["High"]) and float(current["Low"]) >= float(mother["Low"]))
    return {
        "state": "observed" if observed else "absent",
        "bar_completed_at": bars.index[-1].isoformat(),
        "mother_bar_completed_at": bars.index[-2].isoformat(),
        "high": round(float(current["High"]), 4),
        "low": round(float(current["Low"]), 4),
        "breakout_above": round(float(current["High"]), 4),
        "breakdown_below": round(float(current["Low"]), 4),
    }


def _atr_15(bars: pd.DataFrame, lookback: int = 14) -> float | None:
    if len(bars) < lookback + 1:
        return None
    sampled = bars.tail(lookback + 1)
    prior_close = sampled["Close"].shift(1)
    true_range = pd.concat([
        sampled["High"] - sampled["Low"],
        (sampled["High"] - prior_close).abs(),
        (sampled["Low"] - prior_close).abs(),
    ], axis=1).max(axis=1)
    value = _number(true_range.iloc[1:].mean())
    return round(value, 6) if value is not None else None


def completed_4h_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Causally make only full 09:30--13:30 ET four-hour RTH bars."""
    if bars.empty:
        return bars
    source = bars.copy()
    source["session"] = source.index.date
    output: list[pd.DataFrame] = []
    for _, session in source.groupby("session", sort=True):
        session = session.drop(columns="session")
        opening = session.index[0].replace(hour=9, minute=30, second=0, microsecond=0)
        first_window = session[(session.index >= opening) & (session.index < opening + pd.Timedelta(hours=4))]
        # 16 completed 15m bars are required; never label a shortened bar 4H.
        if len(first_window) != 16:
            continue
        output.append(pd.DataFrame({
            "Open": [float(first_window.iloc[0]["Open"])],
            "High": [float(first_window["High"].max())],
            "Low": [float(first_window["Low"].min())],
            "Close": [float(first_window.iloc[-1]["Close"])],
            "Volume": [float(first_window["Volume"].sum())],
        }, index=[opening + pd.Timedelta(hours=4)]))
    return pd.concat(output).sort_index() if output else pd.DataFrame(columns=bars.columns)


def fvg_zones(bars_4h: pd.DataFrame) -> list[dict[str, Any]]:
    zones: list[dict[str, Any]] = []
    for position in range(2, len(bars_4h)):
        first, third = bars_4h.iloc[position - 2], bars_4h.iloc[position]
        if float(first["High"]) < float(third["Low"]):
            zones.append({"direction": "bullish", "low": round(float(first["High"]), 4), "high": round(float(third["Low"]), 4), "formed_at": bars_4h.index[position].isoformat()})
        elif float(first["Low"]) > float(third["High"]):
            zones.append({"direction": "bearish", "low": round(float(third["High"]), 4), "high": round(float(first["Low"]), 4), "formed_at": bars_4h.index[position].isoformat()})
    return zones


def _context(bars: pd.DataFrame, candidate: Mapping[str, Any]) -> dict[str, Any]:
    if bars.empty:
        return {"state": "unavailable"}
    latest_session = bars.index[-1].date()
    session = bars[bars.index.date == latest_session]
    prior = bars[bars.index.date < latest_session]
    prior_close = _number(prior.iloc[-1]["Close"]) if not prior.empty else None
    opening = _number(session.iloc[0]["Open"]) if not session.empty else None
    last_close = _number(session.iloc[-1]["Close"]) if not session.empty else None
    gap = ((opening / prior_close) - 1.0) if opening is not None and prior_close not in (None, 0) else None
    expansion = ((last_close / opening) - 1.0) if opening not in (None, 0) and last_close is not None else None
    primary = candidate.get("primary_catalyst") if isinstance(candidate.get("primary_catalyst"), Mapping) else {}
    verified_event = str(primary.get("status") or "") == "verified_primary_sec"
    objective_gap = gap is not None and abs(gap) >= GAP_MINIMUM
    directional_expansion = expansion is not None and abs(expansion) >= SESSION_EXPANSION_MINIMUM
    return {
        "state": "context_confirmed" if (verified_event or objective_gap) and directional_expansion else "context_incomplete",
        "verified_primary_event": verified_event,
        "objective_open_gap_pct": round(gap * 100, 4) if gap is not None else None,
        "objective_gap_pass": objective_gap,
        "session_directional_move_pct": round(expansion * 100, 4) if expansion is not None else None,
        "directional_expansion_pass": directional_expansion,
        "rule": "verified primary event OR absolute opening gap >=2%, plus absolute session expansion >=1%",
    }


def fvg_reaction(bars: pd.DataFrame) -> dict[str, Any]:
    zones = fvg_zones(completed_4h_bars(bars))
    if not zones or bars.empty:
        return {"state": "no_completed_4h_fvg", "zones": []}
    latest = zones[-1]
    last = bars.iloc[-1]
    atr = _atr_15(bars)
    touched = float(last["Low"]) <= float(latest["high"]) and float(last["High"]) >= float(latest["low"])
    direction = str(latest["direction"])
    close = float(last["Close"])
    reaction = False
    if touched and atr is not None:
        reaction = close >= float(latest["high"]) + atr * REACTION_ATR_MULTIPLE if direction == "bullish" else close <= float(latest["low"]) - atr * REACTION_ATR_MULTIPLE
    return {
        "state": "reaction_observed" if reaction else "zone_touched_waiting_for_reaction" if touched else "active_zone_not_touched",
        "active_zone": latest,
        "atr_15": atr,
        "reaction_rule": "completed 15m close at least 0.50 ATR beyond touched 4H-zone boundary",
        "requires_subsequent_15m_fvg_and_retest": True,
    }


def analyze_symbol(symbol: str, bars: pd.DataFrame, candidate: Mapping[str, Any], as_of: datetime) -> dict[str, Any]:
    completed = _prepared(bars, as_of)
    context = _context(completed, candidate)
    compression = inside_bar(completed)
    fvg = fvg_reaction(completed)
    inside_watch = compression.get("state") == "observed" and context.get("state") == "context_confirmed"
    return {
        "symbol": symbol,
        "status": "ok" if not completed.empty else "data_unavailable",
        "completed_15m_bars": len(completed),
        "context": context,
        "inside_bar": compression,
        "inside_bar_shadow_watch": inside_watch,
        "fvg_4h_to_15m": fvg,
        "decision": "observation_only_not_a_trade_signal",
        "execution_enabled": False,
        "can_submit_orders": False,
        "rank_effect": "none",
        "promotion_eligible": False,
    }


def _read_radar(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_report(*, radar: Mapping[str, Any] | None = None, as_of: datetime | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc)
    radar = radar or _read_radar(RADAR_PATH)
    candidates = [item for item in radar.get("ranked_candidates") or [] if isinstance(item, Mapping)]
    candidate_map = {str(item.get("symbol") or "").upper(): item for item in candidates}
    ranked_symbols = [str(item.get("symbol")).upper() for item in candidates[:MAX_RADAR_SYMBOLS] if item.get("symbol")]
    symbols = list(dict.fromkeys((*CORE_WATCHLIST, *ranked_symbols)))
    items = []
    for symbol in symbols:
        try:
            bars = fetch_recent_bars(symbol, period="5d", interval="15m")
            items.append(analyze_symbol(symbol, bars, candidate_map.get(symbol, {}), as_of))
        except Exception as exc:  # a provider outage must remain visible, not fatal
            items.append({"symbol": symbol, "status": "provider_error", "error": type(exc).__name__, "decision": "observation_only_not_a_trade_signal", "execution_enabled": False, "can_submit_orders": False, "rank_effect": "none", "promotion_eligible": False})
    return {
        "schema_version": 1,
        "strategy_family": "contextual_inside_bar_and_4h_15m_fvg",
        "mode": "shadow_observation_only",
        "generated_at": as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "completed_15m_yfinance_proxy_plus_radar_primary_catalyst_context",
        "preregistration": "research/CONTEXTUAL_BREAKOUT_AND_FVG_MECHANICS_RESEARCH_2026-09-01.md",
        "items": items,
        "execution_enabled": False,
        "can_submit_orders": False,
        "rank_effect": "none",
        "promotion_eligible": False,
        "warning": "Experimental observation only. An inside bar or FVG alone never authorizes a trade.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar", type=Path, default=RADAR_PATH)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report(radar=_read_radar(args.radar))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    observed = sum(item.get("inside_bar_shadow_watch") is True or (item.get("fvg_4h_to_15m") or {}).get("state") == "reaction_observed" for item in report["items"])
    print(f"Contextual pattern observation: symbols={len(report['items'])} observations={observed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
