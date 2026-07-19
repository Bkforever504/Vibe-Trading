#!/usr/bin/env python3
"""Point-in-time SPY ORB challenger lab using underlying bars only.

This research script deliberately does not simulate option prices. A positive
underlying signal is necessary, but not sufficient, evidence for a 0DTE edge.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NY = ZoneInfo("America/New_York")
CACHE = ROOT / "data" / "spy_1m_edge_lab.parquet"
REPORT = Path.home() / ".vibe-trading" / "reports" / "spy-orb-edge-lab.json"


@dataclass(frozen=True)
class LabConfig:
    opening_minutes: int = 5
    last_entry_et: time = time(11, 30)
    reward_risk: float = 1.5
    slippage_bps_per_side: float = 1.0
    shares: int = 100
    range_atr_min: float = 0.03
    range_atr_max: float = 0.30
    relative_open_volume_min: float = 1.0


VARIANTS: dict[str, tuple[str, ...]] = {
    "baseline": (),
    "vwap": ("vwap",),
    "gap_alignment": ("gap",),
    "daily_trend": ("trend",),
    "relative_open_volume": ("rvol",),
    "range_atr": ("range_atr",),
    "vwap_gap": ("vwap", "gap"),
    "vwap_trend": ("vwap", "trend"),
    "vwap_gap_trend": ("vwap", "gap", "trend"),
    "vwap_gap_trend_rvol": ("vwap", "gap", "trend", "rvol"),
    "vwap_gap_trend_range": ("vwap", "gap", "trend", "range_atr"),
    "long_only_vwap_trend": ("long_only", "vwap", "trend"),
    "mwf_social_claim": ("mwf",),
}


def fetch_alpaca(start: str, end: str | None = None) -> pd.DataFrame:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    import scripts.market_data as market_data

    market_data._load_env()  # noqa: SLF001
    if not (market_data._ALPACA_KEY and market_data._ALPACA_SECRET):  # noqa: SLF001
        raise RuntimeError("Alpaca market-data credentials are unavailable")
    client = StockHistoricalDataClient(market_data._ALPACA_KEY, market_data._ALPACA_SECRET)  # noqa: SLF001
    request = StockBarsRequest(
        symbol_or_symbols="SPY",
        timeframe=TimeFrame.Minute,
        start=pd.Timestamp(start, tz=NY).to_pydatetime(),
        end=pd.Timestamp(end, tz=NY).to_pydatetime() if end else datetime.now(NY),
        adjustment="raw",
        feed=DataFeed.IEX,
    )
    frame = client.get_stock_bars(request).df
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.xs("SPY", level="symbol")
    frame.index = pd.to_datetime(frame.index).tz_convert(NY)
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame[["open", "high", "low", "close", "volume"]].sort_index()


def load_bars(start: str, end: str | None, refresh: bool) -> pd.DataFrame:
    if CACHE.exists() and not refresh:
        frame = pd.read_parquet(CACHE)
        frame.index = pd.to_datetime(frame.index)
        return frame
    frame = fetch_alpaca(start, end)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(CACHE)
    return frame


def _features(frame: pd.DataFrame) -> dict[Any, dict[str, float]]:
    grouped = frame.groupby(frame.index.date)
    daily = grouped.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    previous_close = daily["close"].shift(1)
    true_range = pd.concat(
        [daily["high"] - daily["low"], (daily["high"] - previous_close).abs(), (daily["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    daily["atr20"] = true_range.rolling(20).mean().shift(1)
    daily["sma20"] = daily["close"].rolling(20).mean().shift(1)
    daily["prior_close"] = previous_close
    opening_volume = grouped.apply(lambda value: float(value.between_time("09:30", "09:34")["volume"].sum()), include_groups=False)
    daily["opening_volume"] = opening_volume
    daily["opening_volume_mean20"] = opening_volume.rolling(20).mean().shift(1)
    return {day: {key: float(value) if pd.notna(value) else float("nan") for key, value in row.items()} for day, row in daily.iterrows()}


def _passes(filters: tuple[str, ...], context: dict[str, Any], config: LabConfig) -> bool:
    direction = context["direction"]
    if "long_only" in filters and direction != "long":
        return False
    if "mwf" in filters and context["weekday"] not in {0, 2, 4}:
        return False
    if "vwap" in filters and not context["vwap_aligned"]:
        return False
    if "gap" in filters and not context["gap_aligned"]:
        return False
    if "trend" in filters and not context["trend_aligned"]:
        return False
    if "rvol" in filters and not context["relative_open_volume"] >= config.relative_open_volume_min:
        return False
    if "range_atr" in filters and not config.range_atr_min <= context["range_atr"] <= config.range_atr_max:
        return False
    return True


def replay(frame: pd.DataFrame, config: LabConfig | None = None) -> dict[str, list[dict[str, Any]]]:
    config = config or LabConfig()
    frame = frame.between_time("09:30", "16:00").copy()
    features = _features(frame)
    output = {name: [] for name in VARIANTS}
    for day, raw in frame.groupby(frame.index.date):
        stats = features.get(day, {})
        if any(not np.isfinite(stats.get(name, np.nan)) for name in ("prior_close", "atr20", "sma20", "opening_volume_mean20")):
            continue
        bars = raw.resample("5min", origin="start_day", offset="30min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        opening_end = pd.Timestamp.combine(pd.Timestamp(day), time(9, 30)) + pd.Timedelta(minutes=config.opening_minutes - 1)
        candidate_start = pd.Timestamp.combine(pd.Timestamp(day), time(9, 30)) + pd.Timedelta(minutes=config.opening_minutes)
        opening = bars.between_time("09:30", opening_end.strftime("%H:%M"))
        candidates = bars.between_time(candidate_start.strftime("%H:%M"), config.last_entry_et.strftime("%H:%M"))
        if opening.empty or len(candidates) < 2:
            continue
        orb_high, orb_low = float(opening["high"].max()), float(opening["low"].min())
        orb_range = orb_high - orb_low
        if orb_range <= 0:
            continue
        cumulative_pv = ((raw["high"] + raw["low"] + raw["close"]) / 3.0 * raw["volume"]).cumsum()
        cumulative_volume = raw["volume"].cumsum().replace(0, np.nan)
        minute_vwap = cumulative_pv / cumulative_volume
        breakout_pos = None
        direction = None
        candidate_positions = [bars.index.get_loc(timestamp) for timestamp in candidates.index]
        for position in candidate_positions:
            close = float(bars.iloc[position]["close"])
            if close > orb_high:
                breakout_pos, direction = position, "long"
                break
            if close < orb_low:
                breakout_pos, direction = position, "short"
                break
        if breakout_pos is None or breakout_pos + 1 >= len(bars):
            continue
        breakout_at = bars.index[breakout_pos]
        entry_at = bars.index[breakout_pos + 1]
        entry = float(bars.iloc[breakout_pos + 1]["open"])
        stop = orb_low if direction == "long" else orb_high
        risk = entry - stop if direction == "long" else stop - entry
        if risk <= 0:
            continue
        target = entry + config.reward_risk * risk if direction == "long" else entry - config.reward_risk * risk
        breakout_close = float(bars.iloc[breakout_pos]["close"])
        vwap = float(minute_vwap.asof(breakout_at + pd.Timedelta(minutes=4)))
        gap = float(raw.iloc[0]["open"]) - stats["prior_close"]
        context = {
            "direction": direction,
            "weekday": pd.Timestamp(day).weekday(),
            "vwap_aligned": breakout_close > vwap if direction == "long" else breakout_close < vwap,
            "gap_aligned": gap > 0 if direction == "long" else gap < 0,
            "trend_aligned": stats["prior_close"] > stats["sma20"] if direction == "long" else stats["prior_close"] < stats["sma20"],
            "relative_open_volume": stats["opening_volume"] / stats["opening_volume_mean20"],
            "range_atr": orb_range / stats["atr20"],
        }
        future = bars.iloc[breakout_pos + 1:]
        exit_price, outcome = float(future.iloc[-1]["close"]), "eod"
        for _, row in future.iterrows():
            stop_hit = float(row["low"]) <= stop if direction == "long" else float(row["high"]) >= stop
            target_hit = float(row["high"]) >= target if direction == "long" else float(row["low"]) <= target
            if stop_hit:
                exit_price, outcome = stop, "loss"
                break
            if target_hit:
                exit_price, outcome = target, "win"
                break
        gross = exit_price - entry if direction == "long" else entry - exit_price
        costs = 2 * entry * config.slippage_bps_per_side / 10_000.0
        net_r = (gross - costs) / risk
        trade = {
            "date": str(day), "direction": direction, "breakout_at": breakout_at.isoformat(), "entry_at": entry_at.isoformat(),
            "entry": round(entry, 4), "stop": round(stop, 4), "target": round(target, 4), "outcome": outcome,
            "net_r": round(net_r, 4), **{key: round(value, 4) if isinstance(value, float) else value for key, value in context.items()},
        }
        for name, filters in VARIANTS.items():
            if _passes(filters, context, config):
                output[name].append(trade)
    return output


def replay_closing_momentum(frame: pd.DataFrame, slippage_bps_per_side: float = 1.0) -> list[dict[str, Any]]:
    """Test Gao et al.'s first-half-hour direction against the last half-hour."""
    frame = frame.between_time("09:30", "16:00").copy()
    previous_close: float | None = None
    trades: list[dict[str, Any]] = []
    for day, bars in frame.groupby(frame.index.date):
        if previous_close is None:
            previous_close = float(bars.iloc[-1]["close"])
            continue
        first_half = bars.between_time("09:30", "09:59")
        last_half = bars.between_time("15:30", "16:00")
        if first_half.empty or last_half.empty:
            previous_close = float(bars.iloc[-1]["close"])
            continue
        signal_return = float(first_half.iloc[-1]["close"]) / previous_close - 1.0
        direction = "long" if signal_return > 0 else "short"
        entry = float(last_half.iloc[0]["open"])
        exit_price = float(last_half.iloc[-1]["close"])
        gross_bps = (exit_price / entry - 1.0) * 10_000.0
        if direction == "short":
            gross_bps = -gross_bps
        trades.append({
            "date": str(day), "direction": direction, "first_half_return_bps": round(signal_return * 10_000.0, 3),
            "net_bps": round(gross_bps - 2.0 * slippage_bps_per_side, 3),
        })
        previous_close = float(bars.iloc[-1]["close"])
    return trades


def bps_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(trade["net_bps"]) for trade in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    return {
        "trades": len(values), "win_rate": round(len(wins) / len(values), 4) if values else None,
        "expectancy_bps": round(float(np.mean(values)), 3) if values else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses else ("inf" if wins else None),
        "net_bps": round(sum(values), 2),
    }


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(trade["net_r"]) for trade in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(values), "win_rate": round(len(wins) / len(values), 4) if values else None,
        "expectancy_r": round(float(np.mean(values)), 4) if values else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses else ("inf" if wins else None),
        "net_r": round(sum(values), 3), "max_drawdown_r": round(drawdown, 3),
    }


def evaluate(frame: pd.DataFrame, config: LabConfig | None = None) -> dict[str, Any]:
    config = config or LabConfig()
    trades = replay(frame, config)
    rows = []
    for name, values in trades.items():
        split = int(len(values) * 0.70)
        rows.append({
            "variant": name, "filters": list(VARIANTS[name]), "all": metrics(values),
            "train": metrics(values[:split]), "holdout": metrics(values[split:]),
        })
    closing_momentum = replay_closing_momentum(frame, config.slippage_bps_per_side)
    closing_split = int(len(closing_momentum) * 0.70)
    return {
        "schema_version": 1, "mode": "research_only", "execution_enabled": False,
        "instrument_tested": "SPY underlying", "options_pnl_tested": False,
        "config": asdict(config), "rows": rows,
        "first_half_hour_to_close_momentum": {
            "train": bps_metrics(closing_momentum[:closing_split]),
            "holdout": bps_metrics(closing_momentum[closing_split:]),
        },
        "warnings": [
            "IEX bars are not consolidated SIP data.",
            "Option P&L requires historical option bid/ask data and is not inferred from SPY returns.",
            "Variants were preregistered before viewing results; no winning threshold is promoted from this run alone.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=REPORT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    frame = load_bars(args.start, args.end, args.refresh)
    report = evaluate(frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if args.do_print:
        for row in report["rows"]:
            print(f"{row['variant']:<28} train={row['train']} holdout={row['holdout']}")
        print("No orders placed. Options P&L not simulated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
