#!/usr/bin/env python3
"""Investigate liquid-stock bottoms without trying to catch a falling knife.

The scanner separates three different claims:

1. capitulation_watch: forced selling may be present;
2. reversal_confirmed: price and relative strength confirm demand;
3. armed_next_session: a bounded next-session breakout plan exists.

It is read-only. A social post, oversold reading, or ranking score can nominate a
symbol, but none can authorize an order or manufacture a success probability.
"""
from __future__ import annotations

import argparse
import hashlib
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

from scripts.daily_stock_screener import SCREENER_UNIVERSE, completed_bars
from scripts.market_data import data_source, fetch_ohlcv


VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "bottom-reversal-investigator.json"
LOG_PATH = ROOT / "data" / "bottom_reversal_investigator_log.jsonl"
FORMULA_VERSION = "capitulation_sweep_three_day_demand_confirmation_v1"
UNIVERSE = tuple(dict.fromkeys((*SCREENER_UNIVERSE, "MRNA", "PFE")))
SETTINGS = {
    "minimum_history_rows": 90,
    "minimum_price": 5.0,
    "minimum_average_dollar_volume_20d": 100_000_000.0,
    "minimum_drawdown_from_63d_high_pct": 12.0,
    "maximum_rsi2_for_capitulation": 12.0,
    "minimum_down_move_5d_pct": 6.0,
    "minimum_capitulation_volume_ratio": 1.35,
    "minimum_reversal_close_location": 0.60,
    "capitulation_lookback_sessions": 7,
    "minimum_reward_risk": 2.0,
}


def _plan_id(symbol: str, as_of: str, entry: float | None, stop: float | None) -> str | None:
    if entry is None or stop is None:
        return None
    identity = f"bottom_reversal_v1|{symbol}|{as_of}|{entry:.6f}|{stop:.6f}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _rsi(close: pd.Series, period: int = 2) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0).rolling(period).mean()
    losses = (-delta.clip(upper=0)).rolling(period).mean()
    relative = gains / losses.replace(0.0, math.nan)
    return (100.0 - 100.0 / (1.0 + relative)).fillna(50.0)


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.copy().sort_index()
    bars.columns = [str(column).lower() for column in bars.columns]
    close = bars["close"].astype(float)
    volume = bars["volume"].astype(float)
    prior_close = close.shift(1)
    true_range = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - prior_close).abs(), (bars["low"] - prior_close).abs()],
        axis=1,
    ).max(axis=1)
    bars["rsi2"] = _rsi(close)
    bars["ema5"] = close.ewm(span=5, adjust=False).mean()
    bars["atr14"] = true_range.rolling(14).mean()
    bars["prior_low20"] = bars["low"].shift(1).rolling(20).min()
    bars["high63"] = close.shift(1).rolling(63).max()
    bars["drawdown63_pct"] = (close / bars["high63"] - 1.0) * 100.0
    bars["return5_pct"] = close.pct_change(5) * 100.0
    bars["average_dollar_volume20"] = (close * volume).rolling(20).mean()
    bars["volume_ratio"] = volume / volume.shift(1).rolling(20).mean().replace(0.0, math.nan)
    spread = (bars["high"] - bars["low"]).replace(0.0, math.nan)
    bars["close_location"] = ((close - bars["low"]) / spread).fillna(0.5)
    return bars


def _relative_strength(frame: pd.DataFrame, spy: pd.DataFrame) -> tuple[float, float, float]:
    close = frame["close"].astype(float)
    aligned = spy["close"].astype(float).reindex(close.index).ffill()
    if len(close) < 11 or aligned.dropna().shape[0] < 11:
        return 0.0, 0.0, 0.0
    current = (close.iloc[-1] / close.iloc[-6] - 1.0) - (aligned.iloc[-1] / aligned.iloc[-6] - 1.0)
    prior = (close.iloc[-6] / close.iloc[-11] - 1.0) - (aligned.iloc[-6] / aligned.iloc[-11] - 1.0)
    one_day = (close.iloc[-1] / close.iloc[-2] - 1.0) - (aligned.iloc[-1] / aligned.iloc[-2] - 1.0)
    return current * 100.0, prior * 100.0, one_day * 100.0


def evaluate_symbol(symbol: str, frame: pd.DataFrame, spy: pd.DataFrame) -> dict[str, Any]:
    required = int(SETTINGS["minimum_history_rows"])
    if len(frame) < required or not {"open", "high", "low", "close", "volume"}.issubset(frame.columns):
        return {"symbol": symbol, "stage": "blocked", "blockers": ["insufficient_completed_daily_history"]}
    bars = _prepare(frame)
    usable = bars.dropna(subset=["prior_low20", "high63", "atr14", "average_dollar_volume20", "volume_ratio"])
    if usable.empty:
        return {"symbol": symbol, "stage": "blocked", "blockers": ["feature_warmup_incomplete"]}

    price = float(usable["close"].iloc[-1])
    liquid = bool(
        price >= float(SETTINGS["minimum_price"])
        and float(usable["average_dollar_volume20"].iloc[-1]) >= float(SETTINGS["minimum_average_dollar_volume_20d"])
    )
    recent = usable.tail(int(SETTINGS["capitulation_lookback_sessions"]))
    drawdown = recent["drawdown63_pct"] <= -float(SETTINGS["minimum_drawdown_from_63d_high_pct"])
    oversold = (
        (recent["rsi2"] <= float(SETTINGS["maximum_rsi2_for_capitulation"]))
        | (recent["return5_pct"] <= -float(SETTINGS["minimum_down_move_5d_pct"]))
    )
    undercut_reclaim = (
        (recent["low"] <= recent["prior_low20"])
        & (recent["close"] > recent["prior_low20"])
        & (recent["close_location"] >= float(SETTINGS["minimum_reversal_close_location"]))
    )
    participation = recent["volume_ratio"] >= float(SETTINGS["minimum_capitulation_volume_ratio"])
    capitulation_mask = drawdown & oversold & (undercut_reclaim | participation)
    positions = [index for index, value in enumerate(capitulation_mask.tolist()) if bool(value)]
    cap_row = recent.iloc[positions[-1]] if positions else None
    cap_age = len(recent) - 1 - positions[-1] if positions else None

    latest = usable.iloc[-1]
    previous = usable.iloc[-2]
    relative5, prior_relative5, relative1 = _relative_strength(usable, spy)
    demand_confirmation = bool(
        cap_row is not None
        and cap_age is not None
        and cap_age > 0
        and float(latest["close"]) > float(latest["ema5"])
        and float(latest["close"]) > float(previous["high"])
        and (relative5 > prior_relative5 or relative1 > 0.0)
    )
    stage = "reversal_confirmed" if liquid and demand_confirmation else "capitulation_watch" if liquid and cap_row is not None else "none"

    entry = float(latest["high"]) if demand_confirmation else None
    stop = float(recent.tail((cap_age or 0) + 1)["low"].min()) if demand_confirmation else None
    risk = entry - stop if entry is not None and stop is not None else None
    target = entry + float(SETTINGS["minimum_reward_risk"]) * risk if risk is not None and risk > 0 else None
    armed = bool(stage == "reversal_confirmed" and risk is not None and risk > 0)
    if armed:
        stage = "armed_next_session"
    as_of_value = usable.index[-1].date().isoformat()

    blockers: list[str] = []
    if not liquid:
        blockers.append("liquidity_or_price_floor_failed")
    if cap_row is None:
        blockers.append("no_recent_capitulation_reversal")
    if cap_row is not None and not demand_confirmation:
        blockers.append("demand_confirmation_not_complete")

    return {
        "symbol": symbol,
        "stage": stage,
        "as_of": as_of_value,
        "capitulation_date": cap_row.name.date().isoformat() if cap_row is not None else None,
        "capitulation_age_sessions": cap_age,
        "price": round(price, 4),
        "drawdown_from_63d_high_pct": round(float(latest["drawdown63_pct"]), 3),
        "rsi2": round(float(latest["rsi2"]), 2),
        "return_5d_pct": round(float(latest["return5_pct"]), 3),
        "relative_strength_vs_spy_5d_pct": round(relative5, 3),
        "prior_relative_strength_vs_spy_5d_pct": round(prior_relative5, 3),
        "relative_strength_vs_spy_1d_pct": round(relative1, 3),
        "average_dollar_volume_20d": round(float(latest["average_dollar_volume20"]), 2),
        "volume_ratio": round(float(latest["volume_ratio"]), 3),
        "close_location": round(float(latest["close_location"]), 3),
        "next_session_plan": {
            "signal_id": _plan_id(symbol, as_of_value, entry, stop),
            "status": "armed" if armed else "not_armed",
            "entry_trigger": round(entry, 4) if entry is not None else None,
            "invalidation": round(stop, 4) if stop is not None else None,
            "target_2r": round(target, 4) if target is not None else None,
            "order_style": "stop_limit_after_separate_spread_and_gap_revalidation" if armed else None,
        },
        "blockers": blockers,
        "social_alert_authority": "discovery_only",
        "paper_consumable": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(
    *,
    symbols: tuple[str, ...] = UNIVERSE,
    as_of: date | None = None,
    frames: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    source_frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}
    if frames is None:
        for symbol in symbols:
            try:
                source_frames[symbol] = completed_bars(fetch_ohlcv(symbol, lookback_days=700), as_of)
            except Exception as exc:
                failures[symbol] = f"{type(exc).__name__}: {exc}"[:180]
    else:
        source_frames = {symbol: completed_bars(frame, as_of) for symbol, frame in frames.items()}
    spy = source_frames.get("SPY", pd.DataFrame())
    rows = [evaluate_symbol(symbol, source_frames.get(symbol, pd.DataFrame()), spy) for symbol in symbols]
    rank = {"armed_next_session": 0, "reversal_confirmed": 1, "capitulation_watch": 2, "none": 3, "blocked": 4}
    rows.sort(key=lambda row: (rank.get(str(row.get("stage")), 9), float(row.get("rsi2") or 100.0), str(row.get("symbol"))))
    candidates = [row for row in rows if row.get("stage") in {"armed_next_session", "reversal_confirmed", "capitulation_watch"}]
    armed = [row for row in rows if row.get("stage") == "armed_next_session"]
    return {
        "schema_version": 1,
        "formula_version": FORMULA_VERSION,
        "provider": "bottom_reversal_investigator",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": as_of.isoformat(),
        "data_cutoff": "completed_daily_bars_strictly_before_report_date",
        "source": data_source(),
        "mode": "read_only_shadow_investigation",
        "settings": SETTINGS,
        "universe": list(symbols),
        "candidates": candidates,
        "armed_next_session": armed,
        "all_rows": rows,
        "fetch_failures": failures,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
        "success_probability": None,
        "probability_status": "unavailable_until_forward_point_in_time_calibration",
        "live_capital_gate": {
            "status": "blocked",
            "minimum_completed_forward_trades": 50,
            "minimum_distinct_forward_dates": 30,
            "requires_positive_net_expectancy_after_2x_friction": True,
            "requires_positive_bootstrap_expectancy_lower_bound": True,
            "requires_positive_brier_skill_vs_expanding_base_rate": True,
            "requires_calibration_ece_at_most": 0.10,
            "requires_drawdown_within_preregistered_limit": True,
            "requires_explicit_human_approval": True,
            "first_live_stage": "one_share_or_defined_risk_with_max_0_10pct_equity_risk",
        },
        "warnings": [
            "Oversold is not a bottom; confirmation is required after capitulation.",
            "The social post is a discovery lead, not point-in-time performance evidence.",
            "An armed plan still requires next-session gap, spread, catalyst, and portfolio-risk revalidation.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(UNIVERSE))
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    symbols = tuple(dict.fromkeys(value.strip().upper() for value in args.symbols.split(",") if value.strip()))
    report = build_report(symbols=symbols)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Bottom reversal investigation: candidates={len(report['candidates'])} armed={len(report['armed_next_session'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
