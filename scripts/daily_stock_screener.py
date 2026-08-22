#!/usr/bin/env python3
"""Causal Finviz-style stock screener and market posture report.

The screen uses only completed daily bars. News/social inputs are recorded as
context and cannot make a symbol eligible. The module has no broker imports or
order authority.
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

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import data_source, fetch_ohlcv, fetch_vix_term_structure_context


VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "daily-stock-screener.json"
LOG_PATH = ROOT / "data" / "daily_stock_screener_log.jsonl"
MARKET_FORCE_PATH = REPORT_DIR / "market-force-score.json"
CATALYST_PATH = REPORT_DIR / "market-catalyst-calendar.json"

SCREENER_UNIVERSE = (
    "SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLV", "XLE", "XLY", "XLP", "XLU",
    "AAPL", "MSFT", "NVDA", "SMCI", "AVGO", "AMD", "META", "AMZN", "GOOGL", "TSLA", "PLTR", "COIN", "NFLX",
)
SECTOR_ETF = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "SMH", "SMCI": "SMH", "AVGO": "SMH", "AMD": "SMH",
    "META": "XLC", "GOOGL": "XLC", "AMZN": "XLY", "TSLA": "XLY", "NFLX": "XLC",
    "PLTR": "XLK", "COIN": "XLF",
}
FORMULA_VERSION = "finviz_style_pit_trend_relative_strength_liquidity_v1"
SETTINGS = {
    "minimum_price": 10.0,
    "minimum_average_dollar_volume_20d": 250_000_000.0,
    "minimum_atr_pct": 0.75,
    "maximum_atr_pct": 7.0,
    "maximum_long_distance_above_sma20_pct": 8.0,
    "maximum_short_distance_below_sma20_pct": 8.0,
    "maximum_long_rsi14": 75.0,
    "minimum_short_rsi14": 25.0,
    "maximum_distance_from_52w_high_pct": 15.0,
    "minimum_history_rows": 253,
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def completed_bars(frame: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Return bars strictly before as_of so an incomplete live bar is excluded."""
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out.columns = [str(column).lower() for column in out.columns]
    mask = pd.Series(out.index.date < as_of, index=out.index)
    return out.loc[mask].sort_index()


def _rsi14(close: pd.Series) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    denominator = loss.iloc[-1]
    if pd.isna(denominator):
        return 50.0
    if denominator == 0:
        return 100.0
    rs = float(gain.iloc[-1]) / float(denominator)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr_pct(frame: pd.DataFrame) -> float:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous).abs(), (frame["low"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1])
    close = float(frame["close"].iloc[-1])
    return atr / close * 100.0 if close > 0 else 0.0


def _return_pct(close: pd.Series, periods: int) -> float:
    if len(close) <= periods:
        return 0.0
    return (float(close.iloc[-1]) / float(close.iloc[-periods - 1]) - 1.0) * 100.0


def screen_symbol(symbol: str, frame: pd.DataFrame, spy_close: pd.Series) -> dict[str, Any]:
    required = int(SETTINGS["minimum_history_rows"])
    if len(frame) < required or not {"high", "low", "close", "volume"}.issubset(frame.columns):
        return {
            "symbol": symbol,
            "status": "blocked",
            "long_eligible": False,
            "short_eligible": False,
            "score": 0.0,
            "blockers": ["insufficient_completed_daily_history"],
        }

    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    last = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    average_dollar_volume = float((close * volume).tail(20).mean())
    atr_pct = _atr_pct(frame)
    rsi14 = _rsi14(close)
    return_20d = _return_pct(close, 20)
    return_63d = _return_pct(close, 63)
    aligned_spy = spy_close.reindex(close.index).ffill().dropna()
    relative_20d = return_20d - _return_pct(aligned_spy, 20)
    relative_63d = return_63d - _return_pct(aligned_spy, 63)
    distance_sma20 = (last / sma20 - 1.0) * 100.0 if sma20 else 0.0
    high_52w = float(close.tail(252).max())
    distance_high = (last / high_52w - 1.0) * 100.0 if high_52w else 0.0
    prior_volume = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else 0.0
    relative_volume = float(volume.iloc[-1]) / prior_volume if prior_volume > 0 else 0.0

    price_ok = last >= float(SETTINGS["minimum_price"])
    liquidity_ok = average_dollar_volume >= float(SETTINGS["minimum_average_dollar_volume_20d"])
    volatility_ok = float(SETTINGS["minimum_atr_pct"]) <= atr_pct <= float(SETTINGS["maximum_atr_pct"])
    long_trend = last > sma20 > sma50 > sma200
    short_trend = last < sma20 < sma50 < sma200
    long_eligible = bool(
        price_ok and liquidity_ok and volatility_ok and long_trend
        and relative_20d > 0 and return_63d > 0
        and distance_sma20 <= float(SETTINGS["maximum_long_distance_above_sma20_pct"])
        and rsi14 <= float(SETTINGS["maximum_long_rsi14"])
    )
    short_eligible = bool(
        price_ok and liquidity_ok and volatility_ok and short_trend
        and relative_20d < 0 and return_63d < 0
        and distance_sma20 >= -float(SETTINGS["maximum_short_distance_below_sma20_pct"])
        and rsi14 >= float(SETTINGS["minimum_short_rsi14"])
    )

    direction = "long" if long_eligible else "short" if short_eligible else "neutral"
    trend_points = 35.0 if long_trend or short_trend else 15.0 if (last > sma50 > sma200 or last < sma50 < sma200) else 0.0
    relative_points = min(25.0, max(0.0, abs(relative_20d) * 3.0 + abs(relative_63d)))
    liquidity_points = min(20.0, max(0.0, math.log10(max(average_dollar_volume, 1.0) / 10_000_000.0) * 10.0))
    location_points = 10.0 if distance_high >= -float(SETTINGS["maximum_distance_from_52w_high_pct"]) else 0.0
    participation_points = min(10.0, max(0.0, relative_volume * 5.0))
    score = trend_points + relative_points + liquidity_points + location_points + participation_points
    if not price_ok or not liquidity_ok or not volatility_ok:
        score = min(score, 39.0)

    blockers: list[str] = []
    if not price_ok:
        blockers.append("price_below_minimum")
    if not liquidity_ok:
        blockers.append("average_dollar_volume_below_minimum")
    if not volatility_ok:
        blockers.append("atr_outside_operating_band")
    if not (long_trend or short_trend):
        blockers.append("moving_average_stack_not_aligned")
    if not (long_eligible or short_eligible):
        blockers.append("directional_screen_not_qualified")

    return {
        "symbol": symbol,
        "status": "qualified_long" if long_eligible else "qualified_short" if short_eligible else "watch" if price_ok and liquidity_ok else "blocked",
        "direction": direction,
        "long_eligible": long_eligible,
        "short_eligible": short_eligible,
        "score": round(max(0.0, min(100.0, score)), 2),
        "as_of": str(frame.index[-1].date()),
        "price": round(last, 4),
        "average_dollar_volume_20d": round(average_dollar_volume, 2),
        "relative_volume_completed_day": round(relative_volume, 3),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "sma200": round(sma200, 4),
        "distance_from_sma20_pct": round(distance_sma20, 3),
        "distance_from_52w_high_pct": round(distance_high, 3),
        "atr14_pct": round(atr_pct, 3),
        "rsi14": round(rsi14, 2),
        "return_20d_pct": round(return_20d, 3),
        "return_63d_pct": round(return_63d, 3),
        "relative_strength_vs_spy_20d_pct": round(relative_20d, 3),
        "relative_strength_vs_spy_63d_pct": round(relative_63d, 3),
        "blockers": sorted(set(blockers)),
    }


def classify_market_posture(rows: list[dict[str, Any]], vix_term: dict[str, Any]) -> dict[str, Any]:
    usable = [row for row in rows if row.get("status") != "blocked"]
    pct_above50 = 100.0 * sum(float(row.get("price") or 0) > float(row.get("sma50") or math.inf) for row in usable) / len(usable) if usable else 0.0
    pct_above200 = 100.0 * sum(float(row.get("price") or 0) > float(row.get("sma200") or math.inf) for row in usable) / len(usable) if usable else 0.0
    spy = next((row for row in rows if row.get("symbol") == "SPY"), {})
    score = 0
    score += 2 if spy.get("long_eligible") else -2 if spy.get("short_eligible") else 0
    score += 1 if pct_above50 >= 60 and pct_above200 >= 55 else -1 if pct_above50 < 40 or pct_above200 < 40 else 0
    term_regime = str(vix_term.get("regime") or "unavailable")
    score += 1 if term_regime == "contango" else -2 if term_regime == "backwardation" else 0
    classification = "risk_on" if score >= 3 else "risk_off" if score <= -2 else "mixed"
    return {
        "classification": classification,
        "score": score,
        "pct_above_50dma": round(pct_above50, 2),
        "pct_above_200dma": round(pct_above200, 2),
        "spy_screen_status": spy.get("status"),
        "vix_term_regime": term_regime,
        "vix_over_vix3m": vix_term.get("vix_over_vix3m"),
    }


def _sentiment_context(market_force: dict[str, Any], as_of: date) -> dict[str, Any]:
    forces = market_force.get("forces") if isinstance(market_force.get("forces"), list) else []
    narrative = next((row for row in forces if isinstance(row, dict) and row.get("name") == "narrative"), {})
    report_date = str(market_force.get("date") or market_force.get("generated_at") or market_force.get("timestamp") or "")[:10]
    return {
        "status": "context_only" if report_date == as_of.isoformat() else "stale" if market_force else "unavailable",
        "report_date": report_date or None,
        "market_force_classification": market_force.get("classification"),
        "market_force_total_score": market_force.get("total_score"),
        "narrative_direction": narrative.get("direction"),
        "social_can_create_trade": False,
        "social_can_override_hard_gate": False,
    }


def build_report(
    *,
    symbols: tuple[str, ...] = SCREENER_UNIVERSE,
    as_of: date | None = None,
    frames: dict[str, pd.DataFrame] | None = None,
    vix_term: dict[str, Any] | None = None,
    market_force_path: Path = MARKET_FORCE_PATH,
    catalyst_path: Path = CATALYST_PATH,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    source_frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}
    if frames is None:
        for symbol in symbols:
            try:
                source_frames[symbol] = completed_bars(fetch_ohlcv(symbol, lookback_days=900), as_of)
            except Exception as exc:
                failures[symbol] = str(exc)[:180]
    else:
        source_frames = {symbol: completed_bars(frame, as_of) for symbol, frame in frames.items()}

    spy_frame = source_frames.get("SPY", pd.DataFrame())
    spy_close = spy_frame.get("close", pd.Series(dtype=float))
    rows = [screen_symbol(symbol, source_frames.get(symbol, pd.DataFrame()), spy_close) for symbol in symbols]
    rows.sort(key=lambda row: (-float(row.get("score") or 0.0), str(row.get("symbol"))))
    vix_term = vix_term if vix_term is not None else fetch_vix_term_structure_context()
    market_posture = classify_market_posture(rows, vix_term)
    market_force = _read_json(market_force_path)
    catalyst = _read_json(catalyst_path)
    today_context = catalyst.get("today") if isinstance(catalyst.get("today"), dict) else {}
    kill_switches = [
        str(path) for path in (VIBE_HOME / "PORTFOLIO_KILL_SWITCH.json", VIBE_HOME / "MANUAL_RESET_REQUIRED.json")
        if path.exists()
    ]
    operational = bool(spy_frame.shape[0] >= int(SETTINGS["minimum_history_rows"]) and source_frames.get("QQQ", pd.DataFrame()).shape[0] >= int(SETTINGS["minimum_history_rows"]))
    source_by_symbol = {
        symbol: str(frame.attrs.get("data_source") or ("injected" if frames is not None else "unknown"))
        for symbol, frame in source_frames.items()
    }
    return {
        "schema_version": 1,
        "formula_version": FORMULA_VERSION,
        "provider": "daily_stock_screener",
        "mode": "read_only_pretrade_context",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_promote_symbols": False,
        "directional_ranking_authority": "blocked_failed_1d_5d_20d_walk_forward",
        "negative_result_action": "exclude_from_direction_and_priority_do_not_invert_post_hoc",
        "date": as_of.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_cutoff": "completed_daily_bars_strictly_before_report_date",
        "source": data_source(),
        "sources": sorted(set(source_by_symbol.values())),
        "source_by_symbol": source_by_symbol,
        "status": "ok" if operational else "unavailable",
        "settings": SETTINGS,
        "universe": list(symbols),
        "market_posture": market_posture,
        "market_sentiment": _sentiment_context(market_force, as_of),
        "market_research_context": {
            "catalyst_max_impact": today_context.get("max_impact"),
            "catalyst_vetoes": today_context.get("vetoes") or [],
            "portfolio_kill_switches": kill_switches,
        },
        "hard_veto": bool(kill_switches),
        "hard_veto_reasons": ["portfolio_kill_switch_active"] if kill_switches else [],
        "qualified_longs": [row for row in rows if row.get("long_eligible")],
        "qualified_shorts": [row for row in rows if row.get("short_eligible")],
        "rankings": rows,
        "fetch_failures": failures,
        "warnings": [
            "The screen cannot submit orders or promote a symbol.",
            "Social and narrative data are context only and cannot create a trade.",
            "Fundamental filters are omitted because free point-in-time fundamentals are not available for causal testing.",
            "A static liquid universe has survivorship bias and must not be treated as proof of a broad stock-picking edge.",
            "The 1-session, 5-session, and 20-session walk-forward labs produced zero final-period survivors.",
            "Direction labels cannot create, prioritize, promote, or invert a trade; only data/liquidity vetoes have authority.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(SCREENER_UNIVERSE))
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    symbols = tuple(dict.fromkeys(part.strip().upper() for part in args.symbols.split(",") if part.strip()))
    report = build_report(symbols=symbols)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Daily stock screener wrote {args.report_path}")
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
