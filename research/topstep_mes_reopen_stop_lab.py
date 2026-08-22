"""Preregistered fixed-stop variant of the MES reopen-drift study."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

try:
    from research.topstep_mes_reopen_drift_lab import (
        COMMISSION_ROUND_TRIP,
        POINT_VALUE,
        ROOT,
        SOURCE,
        TICK_DOLLARS,
        summarize,
    )
except ModuleNotFoundError:  # Direct execution from the research directory.
    from topstep_mes_reopen_drift_lab import (
        COMMISSION_ROUND_TRIP,
        POINT_VALUE,
        ROOT,
        SOURCE,
        TICK_DOLLARS,
        summarize,
    )


OUT = ROOT / "data" / "topstep_mes_reopen_stop_results.json"
PREREGISTRATION = (
    "research/TOPSTEP_MES_REOPEN_STOP_PREREGISTRATION_2026-08-17.md"
)
STOP_POINTS = 20.0


def _session_marks(quotes: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    marks = quotes.between_time(start, end).copy()
    marks["quote_timestamp"] = marks.index
    return marks.groupby(marks.index.date, sort=True).first().reset_index(drop=True)


def load_stopped_round_trips(path: Path = SOURCE) -> tuple[pd.DataFrame, dict]:
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
    quotes = quotes[
        (quotes["bid_px_00"] > 0)
        & (quotes["ask_px_00"] > 0)
        & (quotes["ask_px_00"] >= quotes["bid_px_00"])
    ].sort_index()
    quotes["symbol"] = quotes["symbol"].astype(str)

    entries = _session_marks(quotes, "18:00:05", "18:00:30").rename(
        columns={
            "quote_timestamp": "entry_timestamp",
            "ask_px_00": "entry_ask",
            "symbol": "entry_symbol",
        }
    )
    exits = _session_marks(quotes, "09:30:00", "09:30:10").rename(
        columns={
            "quote_timestamp": "exit_timestamp",
            "bid_px_00": "scheduled_exit_bid",
            "symbol": "exit_symbol",
        }
    )
    paired = pd.merge_asof(
        entries.sort_values("entry_timestamp"),
        exits.sort_values("exit_timestamp"),
        left_on="entry_timestamp",
        right_on="exit_timestamp",
        direction="forward",
        allow_exact_matches=False,
        tolerance=pd.Timedelta(days=4),
    ).dropna(subset=["exit_timestamp", "entry_ask", "scheduled_exit_bid"])
    paired["same_contract"] = paired["entry_symbol"] == paired["exit_symbol"]
    cross_contract = int((~paired["same_contract"]).sum())
    paired = paired[paired["same_contract"]].copy()

    records = []
    for row in paired.itertuples(index=False):
        path_quotes = quotes.loc[row.entry_timestamp:row.exit_timestamp]
        path_quotes = path_quotes[path_quotes["symbol"] == row.entry_symbol]
        stop_level = float(row.entry_ask) - STOP_POINTS
        stop_quotes = path_quotes[path_quotes["bid_px_00"] <= stop_level]
        stopped = not stop_quotes.empty
        if stopped:
            exit_timestamp = stop_quotes.index[0]
            exit_bid = float(stop_quotes.iloc[0]["bid_px_00"])
        else:
            exit_timestamp = row.exit_timestamp
            exit_bid = float(row.scheduled_exit_bid)
        base_pnl = (exit_bid - float(row.entry_ask)) * POINT_VALUE - COMMISSION_ROUND_TRIP
        records.append(
            {
                "entry_timestamp": row.entry_timestamp,
                "exit_timestamp": exit_timestamp,
                "exit_date": row.exit_timestamp.tz_localize(None).normalize(),
                "entry_symbol": row.entry_symbol,
                "entry_ask": float(row.entry_ask),
                "exit_bid": exit_bid,
                "stopped": stopped,
                "base_pnl": base_pnl,
                "stress_1_pnl": base_pnl - (2 * TICK_DOLLARS),
                "stress_2_pnl": base_pnl - (4 * TICK_DOLLARS),
            }
        )
    return pd.DataFrame(records), {
        "paired_before_contract_check": int(len(paired) + cross_contract),
        "excluded_cross_contract_rows": cross_contract,
        "scored_rows": int(len(records)),
    }


def run(path: Path = SOURCE) -> dict:
    trades, integrity = load_stopped_round_trips(path)
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
            "stop_rate": round(float(frame["stopped"].mean()), 4),
        }
        for name, frame in splits.items()
    }
    full = {
        "base": summarize(trades["base_pnl"]),
        "stress_1": summarize(trades["stress_1_pnl"]),
        "stress_2": summarize(trades["stress_2_pnl"]),
        "stop_rate": round(float(trades["stopped"].mean()), 4),
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
    return {
        "preregistration": PREREGISTRATION,
        "source": str(path.relative_to(ROOT)),
        "stop_points": STOP_POINTS,
        "source_integrity": integrity,
        "splits": split_stats,
        "full_sample": full,
        "promotion_gates": gates,
        "shadow_candidate": all(gates.values()),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    report = run()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
