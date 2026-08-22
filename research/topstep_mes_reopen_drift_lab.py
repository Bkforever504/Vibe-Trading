"""Preregistered Topstep-compliant MES reopen-drift test.

Research only. This module has no broker imports and no execution authority.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "databento" / "mes_v0_bbo1s_rth.parquet"
OUT = ROOT / "data" / "topstep_mes_reopen_drift_results.json"
PREREGISTRATION = (
    "research/TOPSTEP_MES_REOPEN_DRIFT_PREREGISTRATION_2026-08-17.md"
)
POINT_VALUE = 5.0
COMMISSION_ROUND_TRIP = 1.22
TICK_DOLLARS = 1.25


def _valid_quotes(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[
        (frame["bid_px_00"] > 0)
        & (frame["ask_px_00"] > 0)
        & (frame["ask_px_00"] >= frame["bid_px_00"])
    ].sort_index()


def _first_per_day(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.groupby(frame.index.date, sort=True).first()
    result.index = pd.to_datetime(result.index)
    return result


def load_round_trips(path: Path = SOURCE) -> pd.DataFrame:
    table = pq.read_table(
        path,
        columns=["ts_recv", "bid_px_00", "ask_px_00", "symbol"],
    )
    quotes = table.to_pandas()
    if not isinstance(quotes.index, pd.DatetimeIndex):
        raise TypeError(f"expected DatetimeIndex, got {type(quotes.index).__name__}")
    if quotes.index.tz is None:
        quotes.index = quotes.index.tz_localize("UTC")
    quotes.index = quotes.index.tz_convert("America/New_York")
    quotes = _valid_quotes(quotes)

    entries = _first_per_day(quotes.between_time("18:00:05", "18:00:30"))
    exits = _first_per_day(quotes.between_time("09:30:00", "09:30:10"))
    entries = entries.reset_index(names="entry_date").rename(
        columns={
            "ask_px_00": "entry_ask",
            "symbol": "entry_symbol",
        }
    )
    exits = exits.reset_index(names="exit_date").rename(
        columns={
            "bid_px_00": "exit_bid",
            "symbol": "exit_symbol",
        }
    )
    paired = pd.merge_asof(
        entries.sort_values("entry_date"),
        exits.sort_values("exit_date"),
        left_on="entry_date",
        right_on="exit_date",
        direction="forward",
        allow_exact_matches=False,
        tolerance=pd.Timedelta(days=4),
    ).dropna(subset=["exit_date", "entry_ask", "exit_bid"])
    paired["entry_symbol"] = paired["entry_symbol"].astype(str)
    paired["exit_symbol"] = paired["exit_symbol"].astype(str)
    paired["same_contract"] = paired["entry_symbol"] == paired["exit_symbol"]
    paired = paired[paired["same_contract"]].copy()
    paired["base_pnl"] = (
        (paired["exit_bid"] - paired["entry_ask"]) * POINT_VALUE
        - COMMISSION_ROUND_TRIP
    )
    paired["stress_1_pnl"] = paired["base_pnl"] - (2 * TICK_DOLLARS)
    paired["stress_2_pnl"] = paired["base_pnl"] - (4 * TICK_DOLLARS)
    paired["weekday"] = paired["exit_date"].dt.day_name()
    return paired


def summarize(values: pd.Series) -> dict[str, float | int]:
    values = values.dropna().astype(float)
    wins = values[values > 0]
    losses = values[values < 0]
    gross_profit = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    equity = values.cumsum()
    drawdown = equity - equity.cummax()
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    t_stat = float(values.mean() / (std / math.sqrt(len(values)))) if std else 0.0
    return {
        "trades": int(len(values)),
        "avg_pnl": round(float(values.mean()), 3) if len(values) else 0.0,
        "median_pnl": round(float(values.median()), 3) if len(values) else 0.0,
        "win_rate": round(float((values > 0).mean()), 4) if len(values) else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else 0.0,
        "total_pnl": round(float(values.sum()), 2),
        "max_drawdown": round(float(drawdown.min()), 2) if len(drawdown) else 0.0,
        "t_stat_mean": round(t_stat, 3),
    }


def run(path: Path = SOURCE) -> dict:
    trades = load_round_trips(path)
    splits = {
        "development_2024": trades[trades["exit_date"].dt.year == 2024],
        "selection_2025": trades[trades["exit_date"].dt.year == 2025],
        "final_2026": trades[trades["exit_date"].dt.year == 2026],
    }
    split_stats = {
        name: {
            "base": summarize(frame["base_pnl"]),
            "stress_1": summarize(frame["stress_1_pnl"]),
            "stress_2": summarize(frame["stress_2_pnl"]),
        }
        for name, frame in splits.items()
    }
    full = {
        "base": summarize(trades["base_pnl"]),
        "stress_1": summarize(trades["stress_1_pnl"]),
        "stress_2": summarize(trades["stress_2_pnl"]),
    }
    gates = {
        "minimum_split_samples": (
            split_stats["development_2024"]["base"]["trades"] >= 100
            and split_stats["selection_2025"]["base"]["trades"] >= 100
            and split_stats["final_2026"]["base"]["trades"] >= 75
        ),
        "positive_base_each_split": all(
            stats["base"]["avg_pnl"] > 0 for stats in split_stats.values()
        ),
        "positive_full_stress_1": full["stress_1"]["avg_pnl"] > 0,
        "final_base_profit_factor": (
            split_stats["final_2026"]["base"]["profit_factor"] >= 1.05
        ),
        "full_base_profit_factor": full["base"]["profit_factor"] >= 1.05,
        "full_base_drawdown": full["base"]["max_drawdown"] >= -1000.0,
    }
    weekday = {
        day: summarize(frame["base_pnl"])
        for day, frame in trades.groupby("weekday", sort=False)
    }
    return {
        "preregistration": PREREGISTRATION,
        "source": str(path.relative_to(ROOT)),
        "first_exit_date": str(trades["exit_date"].min().date()),
        "last_exit_date": str(trades["exit_date"].max().date()),
        "excluded_cross_contract_rows": "filtered_before scoring",
        "splits": split_stats,
        "full_sample": full,
        "promotion_gates": gates,
        "shadow_candidate": all(gates.values()),
        "weekday_diagnostics_only": weekday,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    report = run()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
