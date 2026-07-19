#!/usr/bin/env python3
"""Replicate the published five-minute ORB rule across liquid underlyings.

The paper's rule enters at the second five-minute candle open in the direction
of the first candle. This is materially different from waiting for a later
breakout. Underlying bars only; no option P&L is inferred.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NY = ZoneInfo("America/New_York")
CACHE_DIR = ROOT / "data" / "liquid_edge_lab"
OUTPUT = Path.home() / ".vibe-trading" / "reports" / "liquid-universe-orb-replication.json"
SYMBOLS = ("QQQ", "TQQQ", "SPY", "IWM")
PAPER_END = "2023-02-17"
OOS_START = "2024-01-01"
RTH_START = "09:30"
RTH_END = "15:55"


@dataclass(frozen=True)
class Variant:
    name: str
    stop_model: str
    target_r: float | None
    require_rvol: bool = False


VARIANTS = (
    Variant("paper_10r", "first_bar", 10.0),
    Variant("paper_eod", "first_bar", None),
    Variant("paper_10r_rvol", "first_bar", 10.0, True),
    Variant("paper_eod_rvol", "first_bar", None, True),
    Variant("posthoc_atr5_eod", "atr5", None),
)


def fetch_bars(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    import scripts.market_data as market_data

    market_data._load_env()  # noqa: SLF001
    if not (market_data._ALPACA_KEY and market_data._ALPACA_SECRET):  # noqa: SLF001
        raise RuntimeError("Alpaca market-data credentials are unavailable")
    client = StockHistoricalDataClient(market_data._ALPACA_KEY, market_data._ALPACA_SECRET)  # noqa: SLF001
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=pd.Timestamp(start, tz=NY).to_pydatetime(),
        end=pd.Timestamp(end, tz=NY).to_pydatetime() if end else datetime.now(NY),
        adjustment="all",
        feed=DataFeed.IEX,
    )
    frame = client.get_stock_bars(request).df
    if frame.empty:
        raise ValueError(f"No five-minute bars returned for {symbol}")
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.xs(symbol, level="symbol")
    frame.index = pd.to_datetime(frame.index).tz_convert(NY)
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame[["open", "high", "low", "close", "volume"]].sort_index()


def load_bars(symbol: str, start: str, end: str | None, refresh: bool) -> pd.DataFrame:
    cache = CACHE_DIR / f"{symbol.lower()}_5m.parquet"
    if cache.exists() and not refresh:
        frame = pd.read_parquet(cache)
        frame.index = pd.to_datetime(frame.index)
        return frame
    frame = fetch_bars(symbol, start, end)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache)
    return frame


def daily_context(frame: pd.DataFrame) -> dict[Any, dict[str, float]]:
    rth = frame.between_time(RTH_START, RTH_END)
    grouped = rth.groupby(rth.index.date)
    daily = grouped.agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    previous_close = daily["close"].shift(1)
    true_range = pd.concat(
        [daily["high"] - daily["low"], (daily["high"] - previous_close).abs(), (daily["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    daily["atr14"] = true_range.rolling(14).mean().shift(1)
    first_volume = grouped["volume"].first()
    daily["first_volume"] = first_volume
    daily["first_volume_mean20"] = first_volume.rolling(20).mean().shift(1)
    return {
        day: {key: float(value) if pd.notna(value) else float("nan") for key, value in row.items()}
        for day, row in daily.iterrows()
    }


def replay(frame: pd.DataFrame, variant: Variant, cost_bps_per_side: float = 1.0) -> list[dict[str, Any]]:
    rth = frame.between_time(RTH_START, RTH_END).copy()
    contexts = daily_context(rth)
    trades: list[dict[str, Any]] = []
    for day, bars in rth.groupby(rth.index.date):
        bars = bars.sort_index()
        if len(bars) < 3 or bars.index[0].time().isoformat(timespec="minutes") != "09:30":
            continue
        first, second = bars.iloc[0], bars.iloc[1]
        if float(first["close"]) == float(first["open"]):
            continue
        context = contexts.get(day, {})
        atr14 = float(context.get("atr14", np.nan))
        volume_mean = float(context.get("first_volume_mean20", np.nan))
        if not np.isfinite(atr14) or not np.isfinite(volume_mean) or volume_mean <= 0:
            continue
        rvol = float(first["volume"]) / volume_mean
        if variant.require_rvol and rvol < 1.0:
            continue
        direction = "long" if float(first["close"]) > float(first["open"]) else "short"
        entry = float(second["open"])
        if variant.stop_model == "first_bar":
            stop = float(first["low"] if direction == "long" else first["high"])
        elif variant.stop_model == "atr5":
            stop_distance = 0.05 * atr14
            stop = entry - stop_distance if direction == "long" else entry + stop_distance
        else:
            raise ValueError(f"Unsupported stop model: {variant.stop_model}")
        risk = entry - stop if direction == "long" else stop - entry
        if risk <= 0:
            continue
        target = None
        if variant.target_r is not None:
            target = entry + variant.target_r * risk if direction == "long" else entry - variant.target_r * risk
        exit_price = float(bars.iloc[-1]["close"])
        outcome = "eod"
        for _, candle in bars.iloc[1:].iterrows():
            stop_hit = float(candle["low"]) <= stop if direction == "long" else float(candle["high"]) >= stop
            target_hit = False
            if target is not None:
                target_hit = float(candle["high"]) >= target if direction == "long" else float(candle["low"]) <= target
            if stop_hit:
                exit_price, outcome = stop, "stop"
                break
            if target_hit:
                exit_price, outcome = float(target), "target"
                break
        gross = exit_price - entry if direction == "long" else entry - exit_price
        cost = 2.0 * entry * cost_bps_per_side / 10_000.0
        trades.append({
            "date": str(day), "direction": direction, "entry": round(entry, 4), "stop": round(stop, 4),
            "target": round(target, 4) if target is not None else None, "outcome": outcome,
            "exit": round(exit_price, 4), "rvol": round(rvol, 4), "risk_points": round(risk, 4),
            "risk_bps": round(risk / entry * 10_000.0, 3),
            "net_return_bps": round((gross - cost) / entry * 10_000.0, 3),
            "net_r": round((gross - cost) / risk, 5),
        })
    return trades


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.asarray([float(trade["net_r"]) for trade in trades], dtype=float)
    if not len(values):
        return {"trades": 0, "win_rate": None, "expectancy_r": None, "expectancy_bps": None, "profit_factor": None, "net_r": 0.0, "max_drawdown_r": 0.0}
    wins, losses = values[values > 0], values[values < 0]
    returns_bps = np.asarray([float(trade.get("net_return_bps", 0.0)) for trade in trades], dtype=float)
    risk_bps = np.asarray([float(trade.get("risk_bps", 0.0)) for trade in trades], dtype=float)
    equity = values.cumsum()
    peaks = np.maximum.accumulate(np.concatenate(([0.0], equity)))
    drawdown = peaks[1:] - equity
    return {
        "trades": int(len(values)), "win_rate": round(float((values > 0).mean()), 4),
        "expectancy_r": round(float(values.mean()), 5),
        "expectancy_bps": round(float(returns_bps.mean()), 3),
        "median_risk_bps": round(float(np.median(risk_bps)), 3),
        "risk_bps_p10": round(float(np.quantile(risk_bps, 0.10)), 3),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if len(losses) else "inf",
        "net_r": round(float(values.sum()), 3), "max_drawdown_r": round(float(drawdown.max(initial=0)), 3),
    }


def moving_block_bootstrap(values: list[float], block: int = 10, samples: int = 5000, seed: int = 20260719) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    if not len(array):
        return {"mean_r": None, "ci95": [None, None], "probability_positive": None}
    block = min(block, len(array))
    starts = np.arange(0, len(array) - block + 1)
    rng = np.random.default_rng(seed)
    means = []
    needed = int(np.ceil(len(array) / block))
    for _ in range(samples):
        sample = np.concatenate([array[start:start + block] for start in rng.choice(starts, size=needed, replace=True)])[:len(array)]
        means.append(float(sample.mean()))
    return {
        "mean_r": round(float(array.mean()), 5),
        "ci95": [round(float(np.quantile(means, 0.025)), 5), round(float(np.quantile(means, 0.975)), 5)],
        "probability_positive": round(float((np.asarray(means) > 0).mean()), 4),
        "block_trades": block,
    }


def evaluate_symbol(symbol: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
    data_start = str(frame.index.min())
    data_end = str(frame.index.max())
    rows = []
    for variant in VARIANTS:
        trades = replay(frame, variant, 1.0)
        stressed = replay(frame, variant, 2.0)
        paper = [trade for trade in trades if trade["date"] <= PAPER_END]
        oos = [trade for trade in trades if trade["date"] >= OOS_START]
        stressed_oos = [trade for trade in stressed if trade["date"] >= OOS_START]
        yearly = {year: metrics([trade for trade in trades if trade["date"].startswith(year)]) for year in sorted({trade["date"][:4] for trade in trades})}
        long_oos = [trade for trade in oos if trade["direction"] == "long"]
        short_oos = [trade for trade in oos if trade["direction"] == "short"]
        bootstrap = moving_block_bootstrap([float(trade["net_r"]) for trade in oos])
        rows.append({
            "symbol": symbol, "variant": variant.name, "rules": variant.__dict__, "paper_window": metrics(paper),
            "post_publication_oos": metrics(oos), "oos_long": metrics(long_oos), "oos_short": metrics(short_oos),
            "double_cost_oos": metrics(stressed_oos), "oos_block_bootstrap": bootstrap, "yearly": yearly,
            "data_coverage": {"start": data_start, "end": data_end, "bars": int(len(frame))},
            "high_confidence_ready": False, "execution_enabled": False,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    rows = []
    errors = []
    for symbol in [item.strip().upper() for item in args.symbols.split(",") if item.strip()]:
        try:
            rows.extend(evaluate_symbol(symbol, load_bars(symbol, args.start, args.end, args.refresh)))
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)[:240]})
    report = {
        "schema_version": 1, "mode": "research_only", "execution_enabled": False,
        "generated_at": datetime.now(NY).isoformat(),
        "paper_replication_end": PAPER_END, "post_publication_oos_start": OOS_START,
        "options_pnl_tested": False, "rows": rows, "errors": errors,
        "warnings": [
            "Alpaca IEX bars are not consolidated SIP data.",
            "Regular-session replay uses 09:30 through the 15:55 five-minute bar; extended-hours bars are excluded.",
            "Cached coverage begins in 2020, so the source paper's 2016-2019 period is not replicated here.",
            "The 2024+ window is post-publication but has now been inspected and cannot be reused as untouched evidence.",
            "The ATR5 variant was reported after sensitivity analysis in the source paper and is explicitly post-hoc.",
            "No social-media P&L claim is used as validation evidence.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if args.do_print:
        for row in rows:
            print(f"{row['symbol']:<5} {row['variant']:<20} paper={row['paper_window']} oos={row['post_publication_oos']}")
        if errors:
            print(f"Errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
