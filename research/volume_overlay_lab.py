#!/usr/bin/env python3
"""Point-in-time volume overlay lab for replayable daily shadow strategies."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_ohlcv
from scripts.mfi_shadow_logger import compute_mfi
from scripts.ttm_squeeze_shadow_logger import compute_squeeze
from scripts.wavetrend_shadow_logger import compute_wavetrend

REPORT = Path.home() / ".vibe-trading" / "reports" / "volume-overlay-lab.json"
CACHE_DIR = ROOT / "data" / "volume_lab"


def _load_strategy(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RSI2 = _load_strategy("research/pine_strategy_lab/examples/rsi2_mean_reversion_python.py", "volume_lab_rsi2")
WR = _load_strategy("research/pine_strategy_lab/examples/williams_r_oversold_python.py", "volume_lab_wr")
KAMA = _load_strategy("research/pine_strategy_lab/examples/kama_trend_python.py", "volume_lab_kama")


def load_daily(symbol: str, refresh: bool = False) -> pd.DataFrame:
    path = CACHE_DIR / f"{symbol.lower()}_daily.parquet"
    if path.exists() and not refresh:
        frame = pd.read_parquet(path)
    else:
        frame = fetch_ohlcv(symbol, lookback_days=3000)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path)
    frame.columns = [str(column).lower() for column in frame.columns]
    frame.index = pd.to_datetime(frame.index)
    return frame[["open", "high", "low", "close", "volume"]].dropna().sort_index()


def volume_features(frame: pd.DataFrame) -> pd.DataFrame:
    high, low, close, volume = frame["high"], frame["low"], frame["close"], frame["volume"].astype(float)
    typical = (high + low + close) / 3.0
    volume_mean20 = volume.rolling(20).mean().shift(1)
    volume_std20 = volume.rolling(20).std(ddof=0).shift(1).replace(0, np.nan)
    direction = np.sign(close.diff()).fillna(0.0)
    obv = (direction * volume).cumsum()
    money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    money_flow_volume = money_flow_multiplier.fillna(0.0) * volume
    cmf20 = money_flow_volume.rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    adl = money_flow_volume.cumsum()
    vpt = (close.pct_change().fillna(0.0) * volume).cumsum()
    force = (close.diff() * volume).ewm(span=13, adjust=False).mean()
    pvi = pd.Series(1000.0, index=frame.index)
    nvi = pd.Series(1000.0, index=frame.index)
    returns = close.pct_change().fillna(0.0)
    for pos in range(1, len(frame)):
        pvi.iloc[pos] = pvi.iloc[pos - 1] * (1 + returns.iloc[pos]) if volume.iloc[pos] > volume.iloc[pos - 1] else pvi.iloc[pos - 1]
        nvi.iloc[pos] = nvi.iloc[pos - 1] * (1 + returns.iloc[pos]) if volume.iloc[pos] < volume.iloc[pos - 1] else nvi.iloc[pos - 1]
    return pd.DataFrame({
        "rvol20": volume / volume_mean20,
        "volume_z20": (volume - volume_mean20) / volume_std20,
        "vroc5": volume.pct_change(5),
        "volume_osc_5_20": volume.ewm(span=5, adjust=False).mean() / volume.ewm(span=20, adjust=False).mean() - 1.0,
        "mavd_5_20": volume.rolling(5).mean() / volume.rolling(20).mean() - 1.0,
        "obv_slope5": obv.diff(5),
        "cmf20": cmf20,
        "mfi14": compute_mfi(frame, 14),
        "vpt_slope5": vpt.diff(5),
        "adl_slope5": adl.diff(5),
        "force13": force,
        "pvi_above_20": pvi > pvi.rolling(20).mean(),
        "nvi_above_20": nvi > nvi.rolling(20).mean(),
        "dollar_volume": typical * volume,
    }, index=frame.index)


FILTERS: dict[str, Callable[[pd.Series, int], bool]] = {
    "none": lambda row, direction: True,
    "rvol_ge_1": lambda row, direction: row.rvol20 >= 1.0,
    "rvol_ge_1_25": lambda row, direction: row.rvol20 >= 1.25,
    "rvol_ge_1_5": lambda row, direction: row.rvol20 >= 1.5,
    "volume_z_ge_0": lambda row, direction: row.volume_z20 >= 0,
    "volume_z_ge_1": lambda row, direction: row.volume_z20 >= 1,
    "vroc5_positive": lambda row, direction: row.vroc5 > 0,
    "volume_osc_positive": lambda row, direction: row.volume_osc_5_20 > 0,
    "mavd_positive": lambda row, direction: row.mavd_5_20 > 0,
    "obv_direction": lambda row, direction: row.obv_slope5 * direction > 0,
    "cmf_direction": lambda row, direction: row.cmf20 * direction > 0,
    "mfi_direction": lambda row, direction: row.mfi14 > 50 if direction > 0 else row.mfi14 < 50,
    "vpt_direction": lambda row, direction: row.vpt_slope5 * direction > 0,
    "adl_direction": lambda row, direction: row.adl_slope5 * direction > 0,
    "force_direction": lambda row, direction: row.force13 * direction > 0,
    "rvol_obv": lambda row, direction: row.rvol20 >= 1 and row.obv_slope5 * direction > 0,
    "rvol_cmf": lambda row, direction: row.rvol20 >= 1 and row.cmf20 * direction > 0,
    "obv_cmf": lambda row, direction: row.obv_slope5 * direction > 0 and row.cmf20 * direction > 0,
    "rvol_vpt": lambda row, direction: row.rvol20 >= 1 and row.vpt_slope5 * direction > 0,
}


def position_trades(frame: pd.DataFrame, position: pd.Series, strategy: str, symbol: str) -> list[dict]:
    position = position.reindex(frame.index).fillna(0).astype(int)
    features = volume_features(frame)
    trades = []
    entry_pos = None
    decision_pos = None
    for pos in range(1, len(frame)):
        if entry_pos is None and position.iloc[pos - 1] == 0 and position.iloc[pos] != 0 and pos + 1 < len(frame):
            decision_pos, entry_pos = pos, pos + 1
            direction = int(np.sign(position.iloc[pos]))
            entry = float(frame.iloc[entry_pos]["open"])
        elif entry_pos is not None and position.iloc[pos - 1] != 0 and position.iloc[pos] == 0 and pos + 1 < len(frame):
            exit_price = float(frame.iloc[pos + 1]["open"])
            raw_return = direction * (exit_price / entry - 1.0)
            trades.append(_trade(strategy, symbol, frame, features, decision_pos, entry_pos, pos + 1, direction, raw_return))
            entry_pos = decision_pos = None
    return trades


def event_trades(
    frame: pd.DataFrame, events: pd.Series, strategy: str, symbol: str,
    hold_bars: int = 5,
) -> list[dict]:
    features = volume_features(frame)
    trades = []
    for decision_pos in np.flatnonzero(events.reindex(frame.index).fillna(0).to_numpy() != 0):
        entry_pos, exit_pos = decision_pos + 1, min(decision_pos + 1 + hold_bars, len(frame) - 1)
        if entry_pos >= len(frame) or exit_pos <= entry_pos:
            continue
        direction = int(np.sign(events.iloc[decision_pos]))
        entry, exit_price = float(frame.iloc[entry_pos]["open"]), float(frame.iloc[exit_pos]["close"])
        raw_return = direction * (exit_price / entry - 1.0)
        trades.append(_trade(strategy, symbol, frame, features, decision_pos, entry_pos, exit_pos, direction, raw_return))
    return trades


def _trade(strategy, symbol, frame, features, decision_pos, entry_pos, exit_pos, direction, raw_return):
    row = features.iloc[decision_pos]
    return {
        "strategy": strategy, "symbol": symbol, "decision_date": str(frame.index[decision_pos].date()),
        "entry_date": str(frame.index[entry_pos].date()), "exit_date": str(frame.index[exit_pos].date()),
        "direction": direction, "raw_return": raw_return,
        "features": {key: (bool(value) if isinstance(value, (bool, np.bool_)) else float(value) if pd.notna(value) else None) for key, value in row.items()},
    }


def build_strategy_trades(symbol: str, frame: pd.DataFrame) -> dict[str, list[dict]]:
    result = {}
    result[f"rsi2_prior_high_{symbol}"] = position_trades(
        frame, RSI2.strategy(frame, rsi_threshold=15, trend_window=200, exit_sma=5, exit_mode="prior_high"),
        "rsi2_prior_high", symbol,
    )
    result[f"williams_r_{symbol}"] = position_trades(
        frame, WR.strategy(frame, wr_window=2 if symbol == "QQQ" else 3, entry_threshold=-90, exit_threshold=-50, max_hold=5, trend_window=0 if symbol == "QQQ" else 200),
        "williams_r", symbol,
    )
    result[f"kama_{symbol}"] = position_trades(
        frame, KAMA.strategy(frame, length=14, fast_length=3, slow_length=20, slope_lookback=3),
        "kama", symbol,
    )
    wt = compute_wavetrend(frame)
    wt_events = pd.Series(0, index=frame.index)
    wt_events[(wt["cross_above"]) & (wt["wt1"] < -53)] = 1
    wt_events[(wt["cross_below"]) & (wt["wt1"] > 53)] = -1
    result[f"wavetrend_{symbol}"] = event_trades(frame, wt_events, "wavetrend", symbol, 5)
    squeeze = compute_squeeze(frame)
    release = squeeze["sqz_on"].shift(1).fillna(False) & squeeze["sqz_off"]
    sq_events = pd.Series(0, index=frame.index)
    sq_events[release & (squeeze["momentum"] > 0) & (squeeze["momentum"] > squeeze["momentum"].shift(1))] = 1
    sq_events[release & (squeeze["momentum"] < 0) & (squeeze["momentum"] < squeeze["momentum"].shift(1))] = -1
    result[f"ttm_squeeze_{symbol}"] = event_trades(frame, sq_events, "ttm_squeeze", symbol, 10)
    mfi = compute_mfi(frame, 14)
    mfi_events = pd.Series(0, index=frame.index)
    mfi_events[(mfi <= 20) & (mfi > mfi.shift(1))] = 1
    mfi_events[(mfi >= 80) & (mfi < mfi.shift(1))] = -1
    result[f"mfi_reversal_{symbol}"] = event_trades(frame, mfi_events, "mfi_reversal", symbol, 5)
    return result


def _metrics(trades: list[dict], cost_bps_per_side: float = 2.0) -> dict:
    values = [trade["direction"] * 0 + trade["raw_return"] - 2 * cost_bps_per_side / 10_000 for trade in trades]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    return {
        "trades": len(values), "win_rate": round(len(wins) / len(values), 4) if values else None,
        "expectancy_bps": round(float(np.mean(values)) * 10_000, 3) if values else None,
        "net_return_sum_pct": round(sum(values) * 100, 2),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses else ("inf" if wins else None),
    }


def evaluate_overlay(trades: list[dict], filter_name: str, cutoff_date: str) -> dict:
    selected = []
    for trade in trades:
        features = pd.Series(trade["features"])
        if features.isna().any() and filter_name != "none":
            continue
        if FILTERS[filter_name](features, int(trade["direction"])):
            selected.append(trade)
    train = [trade for trade in selected if trade["decision_date"] <= cutoff_date]
    holdout = [trade for trade in selected if trade["decision_date"] > cutoff_date]
    return {
        "filter": filter_name, "all": _metrics(selected), "train": _metrics(train),
        "holdout": _metrics(holdout), "double_cost_holdout": _metrics(holdout, 4.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=REPORT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    all_strategies = {}
    for symbol in ("SPY", "QQQ"):
        all_strategies.update(build_strategy_trades(symbol, load_daily(symbol, args.refresh)))
    rows = []
    for strategy, trades in all_strategies.items():
        if not trades:
            continue
        cutoff_date = trades[max(0, int(len(trades) * 0.70) - 1)]["decision_date"]
        for filter_name in FILTERS:
            rows.append({"strategy": strategy, "cutoff_date": cutoff_date, **evaluate_overlay(trades, filter_name, cutoff_date)})
    baselines = {row["strategy"]: row for row in rows if row["filter"] == "none"}
    for row in rows:
        base = baselines[row["strategy"]]
        row["train_uplift_bps"] = round((row["train"]["expectancy_bps"] or 0) - (base["train"]["expectancy_bps"] or 0), 3)
        row["holdout_uplift_bps"] = round((row["holdout"]["expectancy_bps"] or 0) - (base["holdout"]["expectancy_bps"] or 0), 3)
        row["holdout_retention"] = round(row["holdout"]["trades"] / base["holdout"]["trades"], 3) if base["holdout"]["trades"] else 0
    candidates = [
        row for row in rows if row["filter"] != "none"
        and row["train"]["trades"] >= 20 and row["holdout"]["trades"] >= 15
        and row["holdout_retention"] >= 0.25
        and row["train_uplift_bps"] > 0 and row["holdout_uplift_bps"] > 0
        and (row["double_cost_holdout"]["expectancy_bps"] or -1) > 0
    ]
    candidates.sort(key=lambda row: (row["holdout"]["expectancy_bps"], row["holdout"]["trades"]), reverse=True)
    report = {
        "schema_version": 1, "mode": "research_only", "execution_enabled": False,
        "indicator_families": list(FILTERS), "strategy_count": len(all_strategies),
        "configuration_count": len(rows), "rows": rows, "robust_candidates": candidates,
        "limitations": [
            "Daily IEX OHLCV cannot reconstruct bid/ask, option volume imbalance, trade delta, footprint, or order-book imbalance.",
            "WaveTrend, TTM, and MFI use fixed event-study holds because their loggers do not define executable portfolio exits.",
            "Candidate discovery across many filters requires independent forward validation and multiple-testing skepticism.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.do_print:
        print(f"strategies={len(all_strategies)} configs={len(rows)} robust={len(candidates)}")
        for row in candidates[:30]:
            print(f"{row['strategy']:<28} {row['filter']:<22} train={row['train']['expectancy_bps']:>8} holdout={row['holdout']['expectancy_bps']:>8} n={row['holdout']['trades']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
