#!/usr/bin/env python3
"""Intraday volume-indicator overlays for preregistered SPY ORB structures."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.spy_orb_edge_lab import LabConfig, load_bars, metrics, replay

OUTPUT = Path.home() / ".vibe-trading" / "reports" / "spy-orb-volume-lab.json"


def intraday_features(one_minute: pd.DataFrame) -> pd.DataFrame:
    bars = one_minute.between_time("09:30", "16:00").resample(
        "5min", origin="start_day", offset="30min"
    ).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    day = pd.Series(bars.index.date, index=bars.index)
    bucket = pd.Series(bars.index.time, index=bars.index)
    expected_bar = bars["volume"].groupby(bucket).transform(lambda values: values.rolling(20).mean().shift(1))
    bars["cumulative_volume"] = bars["volume"].groupby(day).cumsum()
    expected_cumulative = bars["cumulative_volume"].groupby(bucket).transform(lambda values: values.rolling(20).mean().shift(1))
    direction = np.sign(bars["close"].diff()).where(day == day.shift(1), 0.0).fillna(0.0)
    obv_step = direction * bars["volume"]
    obv = obv_step.groupby(day).cumsum()
    multiplier = ((bars["close"] - bars["low"]) - (bars["high"] - bars["close"])) / (bars["high"] - bars["low"]).replace(0, np.nan)
    mfv = multiplier.fillna(0.0) * bars["volume"]
    adl = mfv.groupby(day).cumsum()
    intraday_return = bars["close"].pct_change().where(day == day.shift(1), 0.0).fillna(0.0)
    vpt = (intraday_return * bars["volume"]).groupby(day).cumsum()
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    positive_flow = (typical * bars["volume"]).where((typical.diff() > 0) & (day == day.shift(1)), 0.0)
    negative_flow = (typical * bars["volume"]).where((typical.diff() < 0) & (day == day.shift(1)), 0.0)
    pos5 = positive_flow.groupby(day).rolling(5).sum().reset_index(level=0, drop=True)
    neg5 = negative_flow.groupby(day).rolling(5).sum().reset_index(level=0, drop=True).replace(0, np.nan)
    mfi5 = 100 - 100 / (1 + pos5 / neg5)
    cmf5_num = mfv.groupby(day).rolling(5).sum().reset_index(level=0, drop=True)
    cmf5_den = bars["volume"].groupby(day).rolling(5).sum().reset_index(level=0, drop=True).replace(0, np.nan)
    return pd.DataFrame({
        "bar_rvol20": bars["volume"] / expected_bar,
        "cumulative_rvol20": bars["cumulative_volume"] / expected_cumulative,
        "obv_slope3": obv.groupby(day).diff(3),
        "cmf5": cmf5_num / cmf5_den,
        "mfi5": mfi5,
        "vpt_slope3": vpt.groupby(day).diff(3),
        "adl_slope3": adl.groupby(day).diff(3),
        "volume_acceleration": bars["volume"] / bars["volume"].groupby(day).shift(1).replace(0, np.nan),
    }, index=bars.index)


def augment(trades: list[dict], features: pd.DataFrame) -> list[dict]:
    output = []
    for trade in trades:
        timestamp = pd.Timestamp(trade["breakout_at"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("America/New_York")
        else:
            timestamp = timestamp.tz_convert("America/New_York")
        if timestamp not in features.index:
            continue
        row = features.loc[timestamp]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        output.append({**trade, "volume_features": {key: float(value) if pd.notna(value) else None for key, value in row.items()}})
    return output


FILTERS = {
    "none": lambda row, direction: True,
    "bar_rvol_ge_1": lambda row, direction: row.bar_rvol20 >= 1,
    "bar_rvol_ge_1_25": lambda row, direction: row.bar_rvol20 >= 1.25,
    "cumulative_rvol_ge_1": lambda row, direction: row.cumulative_rvol20 >= 1,
    "cumulative_rvol_ge_1_25": lambda row, direction: row.cumulative_rvol20 >= 1.25,
    "volume_acceleration": lambda row, direction: row.volume_acceleration > 1,
    "obv_direction": lambda row, direction: row.obv_slope3 * direction > 0,
    "cmf_direction": lambda row, direction: row.cmf5 * direction > 0,
    "mfi_direction": lambda row, direction: row.mfi5 > 50 if direction > 0 else row.mfi5 < 50,
    "vpt_direction": lambda row, direction: row.vpt_slope3 * direction > 0,
    "adl_direction": lambda row, direction: row.adl_slope3 * direction > 0,
    "cum_rvol_obv": lambda row, direction: row.cumulative_rvol20 >= 1 and row.obv_slope3 * direction > 0,
    "cum_rvol_cmf": lambda row, direction: row.cumulative_rvol20 >= 1 and row.cmf5 * direction > 0,
    "cum_rvol_vpt": lambda row, direction: row.cumulative_rvol20 >= 1 and row.vpt_slope3 * direction > 0,
}


def _selected(trades: list[dict], name: str) -> list[dict]:
    result = []
    for trade in trades:
        row = pd.Series(trade["volume_features"])
        if name != "none" and row.isna().any():
            continue
        direction = 1 if trade["direction"] == "long" else -1
        if FILTERS[name](row, direction):
            result.append(trade)
    return result


def adjusted_metrics(trades: list[dict], extra_bps_per_side: float = 0.0) -> dict:
    adjusted = []
    for trade in trades:
        risk = abs(float(trade["entry"]) - float(trade["stop"]))
        extra_r = 2 * float(trade["entry"]) * extra_bps_per_side / 10_000 / risk if risk > 0 else 0
        adjusted.append({**trade, "net_r": float(trade["net_r"]) - extra_r})
    return metrics(adjusted)


def main() -> int:
    bars = load_bars("2022-01-01", None, False)
    features = intraday_features(bars)
    rows = []
    for opening_minutes in (5, 15):
        for reward_risk in (1.0, 1.5, 2.0):
            for cutoff in (time(10, 30), time(11, 30)):
                config = replace(LabConfig(), opening_minutes=opening_minutes, reward_risk=reward_risk, last_entry_et=cutoff)
                base_trades = replay(bars, config)["baseline"]
                trades = augment(base_trades, features)
                if not trades:
                    continue
                cutoff_date = trades[max(0, int(len(trades) * 0.70) - 1)]["date"]
                config_rows = []
                for filter_name in FILTERS:
                    selected = _selected(trades, filter_name)
                    train = [trade for trade in selected if trade["date"] <= cutoff_date]
                    holdout = [trade for trade in selected if trade["date"] > cutoff_date]
                    config_rows.append({
                        "filter": filter_name, "train": adjusted_metrics(train), "holdout": adjusted_metrics(holdout),
                        "double_cost_holdout": adjusted_metrics(holdout, 1.0),
                    })
                baseline = next(row for row in config_rows if row["filter"] == "none")
                for row in config_rows:
                    row.update({
                        "opening_minutes": opening_minutes, "reward_risk": reward_risk,
                        "last_entry_et": cutoff.isoformat(timespec="minutes"), "cutoff_date": cutoff_date,
                        "train_uplift_r": round((row["train"]["expectancy_r"] or 0) - (baseline["train"]["expectancy_r"] or 0), 4),
                        "holdout_uplift_r": round((row["holdout"]["expectancy_r"] or 0) - (baseline["holdout"]["expectancy_r"] or 0), 4),
                        "holdout_retention": round(row["holdout"]["trades"] / baseline["holdout"]["trades"], 3) if baseline["holdout"]["trades"] else 0,
                    })
                    rows.append(row)
    candidates = [
        row for row in rows if row["filter"] != "none" and row["train"]["trades"] >= 50
        and row["holdout"]["trades"] >= 25 and row["holdout_retention"] >= 0.25
        and row["train_uplift_r"] > 0 and row["holdout_uplift_r"] > 0
        and (row["double_cost_holdout"]["expectancy_r"] or -1) > 0
    ]
    candidates.sort(key=lambda row: (row["holdout"]["expectancy_r"], row["holdout"]["trades"]), reverse=True)
    report = {
        "mode": "research_only", "execution_enabled": False, "configurations": len(rows),
        "indicator_families": list(FILTERS), "robust_candidates": candidates, "rows": rows,
        "limitations": ["IEX bars only", "OHLCV does not contain aggressor volume or order-book delta", "multiple-testing discovery requires untouched forward validation"],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"configs={len(rows)} robust={len(candidates)}")
    for row in candidates[:30]:
        print(f"OR={row['opening_minutes']:>2} RR={row['reward_risk']:.1f} cut={row['last_entry_et']} {row['filter']:<24} train={row['train']['expectancy_r']:>7} holdout={row['holdout']['expectancy_r']:>7} n={row['holdout']['trades']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
