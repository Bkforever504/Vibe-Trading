"""Free proxy holdout for the discovered MES reopen weekday candidate."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from research.topstep_mes_reopen_drift_lab import ROOT, summarize


OUT = ROOT / "data" / "topstep_mes_reopen_weekday_proxy_holdout.json"
PREREGISTRATION = "research/TOPSTEP_MES_REOPEN_WEEKDAY_HOLDOUT_2026-08-17.md"
START = "2026-07-18"
END = "2026-08-18"
ELIGIBLE_WEEKDAYS = {"Monday", "Wednesday", "Thursday"}
POINT_VALUE = 5.0
CONSERVATIVE_COST = 6.22


def _flatten(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    return frame


def build_trades(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _flatten(frame).dropna(subset=["Open", "Close"]).sort_index()
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    else:
        frame.index = frame.index.tz_convert("America/New_York")

    entries = frame.between_time("18:00", "18:15").copy()
    entries["entry_timestamp"] = entries.index
    entries = entries.groupby(entries.index.date, sort=True).first().reset_index(drop=True)
    entries = entries[["entry_timestamp", "Close"]].rename(columns={"Close": "entry_close"})

    exits = frame.between_time("09:30", "09:30").copy()
    exits["exit_timestamp"] = exits.index
    exits = exits.groupby(exits.index.date, sort=True).first().reset_index(drop=True)
    exits = exits[["exit_timestamp", "Open"]].rename(columns={"Open": "exit_open"})

    trades = pd.merge_asof(
        entries.sort_values("entry_timestamp"),
        exits.sort_values("exit_timestamp"),
        left_on="entry_timestamp",
        right_on="exit_timestamp",
        direction="forward",
        allow_exact_matches=False,
        tolerance=pd.Timedelta(days=4),
    ).dropna()
    trades["exit_weekday"] = trades["exit_timestamp"].dt.day_name()
    trades["eligible"] = trades["exit_weekday"].isin(ELIGIBLE_WEEKDAYS)
    trades["pnl"] = (
        (trades["exit_open"] - trades["entry_close"]) * POINT_VALUE
        - CONSERVATIVE_COST
    )
    return trades


def run(frame: pd.DataFrame | None = None) -> dict:
    if frame is None:
        frame = yf.download(
            "MES=F",
            start=START,
            end=END,
            interval="5m",
            auto_adjust=False,
            prepost=True,
            progress=False,
        )
    trades = build_trades(frame)
    eligible = trades[trades["eligible"]]
    stats = summarize(eligible["pnl"])
    gates = {
        "minimum_trades": stats["trades"] >= 10,
        "positive_expectancy": stats["avg_pnl"] > 0,
        "profit_factor": stats["profit_factor"] >= 1.05,
        "max_drawdown": stats["max_drawdown"] >= -500.0,
    }
    return {
        "preregistration": PREREGISTRATION,
        "instrument": "MES=F Yahoo 5m extended-hours proxy",
        "holdout_start": START,
        "holdout_end_exclusive": END,
        "eligible_exit_weekdays": sorted(ELIGIBLE_WEEKDAYS),
        "conservative_cost_per_trade": CONSERVATIVE_COST,
        "all_sessions": summarize(trades["pnl"]),
        "eligible_sessions": stats,
        "support_gates": gates,
        "proxy_supportive": all(gates.values()),
        "requires_executable_bbo_holdout": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    report = run()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
