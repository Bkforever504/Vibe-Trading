#!/usr/bin/env python3
"""Preregistered cross-sectional weekly/monthly volume screen experiment."""
from __future__ import annotations

import argparse
import json
import math
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "htf_volume_screen_lab"
OUTPUT = Path.home() / ".vibe-trading" / "reports" / "higher-timeframe-volume-screen-lab.json"
DEFAULT_SYMBOLS = (
    "SPY QQQ IWM DIA SMH XLK XLF XLE XLV XLY XLP TLT GLD SLV "
    "AAPL MSFT NVDA AMZN META GOOGL TSLA AMD JPM BAC XOM CVX WMT COST HD"
).split()
DEV_END = "2022-12-31"
SELECTION_END = "2023-12-31"


@dataclass(frozen=True)
class Variant:
    name: str
    frequency: str
    volume_rule: str
    require_positive_period: bool = True
    require_dual_trend: bool = False
    hold_days: int = 5
    top_n: int = 5


VARIANTS = (
    Variant("weekly_price_trend_baseline", "weekly", "none"),
    Variant("weekly_rvol_125", "weekly", "rvol_125"),
    Variant("weekly_volume_acceleration", "weekly", "acceleration"),
    Variant("weekly_rvol_125_dual_trend", "weekly", "rvol_125", require_dual_trend=True),
    Variant("monthly_price_trend_baseline", "monthly", "none", hold_days=20),
    Variant("monthly_rvol_125", "monthly", "rvol_125", hold_days=20),
)


def load_symbol(symbol: str, start: str, end: str | None, refresh: bool) -> pd.DataFrame:
    path = CACHE_DIR / f"{symbol.lower()}_{start}_{end or 'latest'}.parquet"
    if path.exists() and not refresh:
        frame = pd.read_parquet(path)
    else:
        import yfinance as yf
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
        if frame.empty:
            raise ValueError(f"no data for {symbol}")
        frame.columns = [column.lower() if isinstance(column, str) else column[0].lower() for column in frame.columns]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path)
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame[["open", "high", "low", "close", "volume"]].dropna().sort_index()


def period_candidates(symbol: str, frame: pd.DataFrame, frequency: str) -> list[dict[str, Any]]:
    rule = "W-FRI" if frequency == "weekly" else "ME"
    volume_window = 20 if frequency == "weekly" else 12
    trend_window = 20 if frequency == "weekly" else 10
    return_window = 4 if frequency == "weekly" else 3
    grouped = frame.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    grouped = grouped[grouped.index.normalize() <= frame.index[-1].normalize()]
    rows = []
    for pos in range(max(volume_window + 1, trend_window, return_window), len(grouped)):
        period_end = grouped.index[pos]
        eligible_daily = frame.index[frame.index <= period_end]
        if eligible_daily.empty:
            continue
        decision_date = eligible_daily[-1]
        decision_pos = frame.index.get_loc(decision_date)
        entry_pos = decision_pos + 1
        if entry_pos >= len(frame):
            continue
        prior_volume = grouped["volume"].iloc[pos - volume_window:pos]
        prior_average = float(prior_volume.mean())
        current_volume = float(grouped["volume"].iloc[pos])
        rvol = current_volume / prior_average if prior_average > 0 else 0.0
        close = float(grouped["close"].iloc[pos])
        trend_average = float(grouped["close"].iloc[pos - trend_window + 1:pos + 1].mean())
        period_return = close / float(grouped["close"].iloc[pos - 1]) - 1.0
        momentum = close / float(grouped["close"].iloc[pos - return_window]) - 1.0
        monthly = frame.loc[:decision_date].resample("ME").agg({"close": "last"}).dropna()
        completed_monthly = monthly[monthly.index <= decision_date.normalize()]
        monthly_trend = (
            len(completed_monthly) >= 10
            and float(completed_monthly["close"].iloc[-1]) > float(completed_monthly["close"].tail(10).mean())
        )
        rows.append({
            "symbol": symbol,
            "decision_date": str(decision_date.date()),
            "entry_pos": entry_pos,
            "rvol": rvol,
            "volume_acceleration": current_volume > float(grouped["volume"].iloc[pos - 1]),
            "price_trend": close > trend_average,
            "monthly_trend": monthly_trend,
            "period_return": period_return,
            "momentum": momentum,
        })
    return rows


def select_and_replay(
    frames: dict[str, pd.DataFrame], candidates: list[dict[str, Any]], variant: Variant, cost_bps: float
) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        if not row["price_trend"]:
            continue
        if variant.require_dual_trend and not row["monthly_trend"]:
            continue
        if variant.require_positive_period and row["period_return"] <= 0:
            continue
        if variant.volume_rule == "rvol_125" and row["rvol"] < 1.25:
            continue
        if variant.volume_rule == "acceleration" and not (row["rvol"] >= 1.0 and row["volume_acceleration"]):
            continue
        by_date.setdefault(row["decision_date"], []).append(row)

    portfolios = []
    for decision_date, rows in sorted(by_date.items()):
        rank_key = "momentum" if variant.volume_rule == "none" else "rvol"
        selected = sorted(rows, key=lambda row: row[rank_key], reverse=True)[:variant.top_n]
        returns = []
        symbols = []
        for row in selected:
            frame = frames[row["symbol"]]
            entry_pos = int(row["entry_pos"])
            exit_pos = min(entry_pos + variant.hold_days - 1, len(frame) - 1)
            if exit_pos <= entry_pos:
                continue
            entry = float(frame["open"].iloc[entry_pos])
            exit_price = float(frame["close"].iloc[exit_pos])
            returns.append(exit_price / entry - 1.0 - cost_bps / 10_000)
            symbols.append(row["symbol"])
        if returns:
            portfolios.append({
                "decision_date": decision_date,
                "return": float(np.mean(returns)),
                "symbol_count": len(returns),
                "symbols": symbols,
            })
    return portfolios


def bootstrap(values: list[float], samples: int = 3000, seed: int = 20260720) -> dict[str, Any]:
    if len(values) < 10:
        return {"ci95_bps": [None, None], "probability_positive": None}
    array = np.asarray(values)
    block = min(max(2, int(math.sqrt(len(array)))), len(array))
    starts = np.arange(0, len(array) - block + 1)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(samples):
        chunks = [array[start:start + block] for start in rng.choice(starts, size=math.ceil(len(array) / block), replace=True)]
        means.append(float(np.concatenate(chunks)[:len(array)].mean()))
    return {
        "ci95_bps": [round(float(np.quantile(means, 0.025)) * 10_000, 3), round(float(np.quantile(means, 0.975)) * 10_000, 3)],
        "probability_positive": round(float((np.asarray(means) > 0).mean()), 4),
        "block_periods": block,
    }


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.asarray([row["return"] for row in rows], dtype=float)
    if not len(values):
        return {"periods": 0, "expectancy_bps": None, "win_rate": None, "profit_factor": None, "max_drawdown_pct": None}
    wins, losses = values[values > 0], values[values < 0]
    equity = np.cumprod(1 + values)
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    drawdown = equity / peak - 1.0
    remove_count = max(1, math.ceil(len(values) * 0.01))
    trimmed = np.sort(values)[:-remove_count]
    return {
        "periods": int(len(values)),
        "underlying_signals": int(sum(row["symbol_count"] for row in rows)),
        "expectancy_bps": round(float(values.mean()) * 10_000, 3),
        "win_rate": round(float((values > 0).mean()), 4),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if len(losses) else "inf",
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 3),
        "top_one_pct_removed_expectancy_bps": round(float(trimmed.mean()) * 10_000, 3) if len(trimmed) else None,
        "bootstrap": bootstrap(values.tolist()),
    }


def split_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "development_2015_2022": metrics([row for row in rows if row["decision_date"] <= DEV_END]),
        "selection_2023": metrics([row for row in rows if DEV_END < row["decision_date"] <= SELECTION_END]),
        "final_2024_plus": metrics([row for row in rows if row["decision_date"] > SELECTION_END]),
    }


def pass_checks(row: dict[str, Any], baseline: dict[str, Any]) -> dict[str, bool]:
    final = row["final_2024_plus"]
    stress = row["triple_cost_final_2024_plus"]
    bootstrap_low = final.get("bootstrap", {}).get("ci95_bps", [None])[0]
    return {
        "positive_all_windows": all(
            (row[window].get("expectancy_bps") or 0) > 0
            for window in ("development_2015_2022", "selection_2023", "final_2024_plus")
        ),
        "beats_final_price_only_baseline": (
            (final.get("expectancy_bps") or 0) > (baseline["final_2024_plus"].get("expectancy_bps") or 0)
        ),
        "positive_at_30bps_cost": (stress.get("expectancy_bps") or 0) > 0,
        "positive_without_top_one_pct": (final.get("top_one_pct_removed_expectancy_bps") or 0) > 0,
        "positive_bootstrap_lower_bound": bootstrap_low is not None and bootstrap_low > 0,
    }


def run_lab(symbols: list[str], start: str, end: str | None, refresh: bool) -> dict[str, Any]:
    frames, errors = {}, []
    for symbol in symbols:
        try:
            frames[symbol] = load_symbol(symbol, start, end, refresh)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)[:200]})
    candidate_cache = {
        frequency: [row for symbol, frame in frames.items() for row in period_candidates(symbol, frame, frequency)]
        for frequency in ("weekly", "monthly")
    }
    rows = []
    for variant in VARIANTS:
        base = select_and_replay(frames, candidate_cache[variant.frequency], variant, cost_bps=10.0)
        stressed = select_and_replay(frames, candidate_cache[variant.frequency], variant, cost_bps=30.0)
        row = {"variant": variant.name, "rules": variant.__dict__, **split_metrics(base)}
        row["triple_cost_final_2024_plus"] = metrics([item for item in stressed if item["decision_date"] > SELECTION_END])
        rows.append(row)
    baselines = {row["variant"]: row for row in rows if "baseline" in row["variant"]}
    for row in rows:
        baseline_name = "weekly_price_trend_baseline" if row["variant"].startswith("weekly") else "monthly_price_trend_baseline"
        baseline = baselines[baseline_name]
        row["final_uplift_vs_price_only_bps"] = round(
            (row["final_2024_plus"]["expectancy_bps"] or 0) - (baseline["final_2024_plus"]["expectancy_bps"] or 0), 3
        )
        row["pass_checks"] = pass_checks(row, baseline)
        row["high_confidence_ready"] = "baseline" not in row["variant"] and all(row["pass_checks"].values())
    return {
        "schema_version": 1,
        "mode": "research_only_preregistered_family",
        "execution_enabled": False,
        "can_submit_orders": False,
        "data_window": {"start": start, "end": end, "development_end": DEV_END, "selection_end": SELECTION_END},
        "symbols_requested": symbols,
        "symbols_loaded": sorted(frames),
        "errors": errors,
        "configuration_count": len(rows),
        "rows": rows,
        "warnings": [
            "Current large/liquid universe creates survivorship bias; results cannot authorize execution.",
            "Adjusted Yahoo bars are research data, not executable quote data.",
            "The 2024+ period is a labeled final test for this preregistered family but has been consumed by other project research.",
            "Date-level equal-weight portfolios prevent correlated same-day symbols from inflating sample size.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=(date.today() + timedelta(days=1)).isoformat())
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = run_lab([item.strip().upper() for item in args.symbols.split(",") if item.strip()], args.start, args.end, args.refresh)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Higher-timeframe volume report wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
