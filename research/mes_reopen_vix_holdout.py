#!/usr/bin/env python3
"""Reproduce the causal MES reopen-to-open VIX-filter evidence.

The filter is frozen. This script performs no parameter search and has no
broker or execution imports.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_overnight_holdout import (
    FRICTION_ROUND_TRIP,
    MULT,
    fetch_vix,
    load_mes,
    stats,
)


OUT = ROOT / "data" / "mes_reopen_vix_holdout.json"
PREREGISTRATION = "research/MES_REOPEN_VIX_FILTER_PREREGISTRATION_2026-08-17.md"
VIX_CAP = 18.0
PRIOR_MOVE_FLOOR = -0.01


def _daily(series: pd.Series) -> pd.Series:
    series = series.copy()
    series.index = series.index.tz_localize(None).normalize()
    return series


def build_trades(bars: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    et = bars.tz_convert("America/New_York")
    close_1600 = _daily(
        et.between_time("15:59:00", "16:00:00")["close"].resample("1D").last().dropna()
    )
    entry_1800 = _daily(
        et.between_time("18:00:00", "18:01:00")["open"].resample("1D").first().dropna()
    )
    exit_0930 = _daily(
        et.between_time("09:30:00", "09:31:00")["open"].resample("1D").first().dropna()
    )

    entries = entry_1800.rename("entry").rename_axis("entry_date").reset_index()
    exits = exit_0930.rename("exit").rename_axis("exit_date").reset_index()
    trades = pd.merge_asof(
        entries.sort_values("entry_date"),
        exits.sort_values("exit_date"),
        left_on="entry_date",
        right_on="exit_date",
        direction="forward",
        allow_exact_matches=False,
        tolerance=pd.Timedelta(days=4),
    ).dropna()
    trades = trades.set_index("entry_date")
    trades["mes_close_1600"] = close_1600.reindex(trades.index)
    trades["prior_move"] = close_1600.pct_change().reindex(trades.index)
    trades["vix_close"] = vix.reindex(trades.index, method="ffill")
    trades = trades.dropna(subset=["mes_close_1600", "prior_move", "vix_close"])
    trades = trades[
        (trades.index.dayofweek <= 3)
        & (trades["vix_close"] <= VIX_CAP)
        & (trades["prior_move"] >= PRIOR_MOVE_FLOOR)
    ].copy()
    trades["net_dollar"] = (
        (trades["exit"] - trades["entry"]) * MULT - FRICTION_ROUND_TRIP
    )
    trades["notional"] = trades["entry"] * MULT
    trades["net_return"] = trades["net_dollar"] / trades["notional"]
    return trades


def run(bars: pd.DataFrame | None = None, vix: pd.Series | None = None) -> dict:
    trades = build_trades(load_mes() if bars is None else bars, fetch_vix() if vix is None else vix)
    train = trades[trades.index <= "2024-12-31"]
    test = trades[trades.index >= "2025-01-01"]
    return {
        "preregistration": PREREGISTRATION,
        "rule": {
            "entry": "MES 18:00 ET reopen",
            "exit": "next MES 09:30 ET open",
            "vix_cap": VIX_CAP,
            "prior_move_floor": PRIOR_MOVE_FLOOR,
            "eligible_entry_weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday"],
            "friction_round_trip": FRICTION_ROUND_TRIP,
        },
        "train_2022_2024": stats(train),
        "test_2025_2026": stats(test),
        "full": stats(trades),
        "interpretation": "retrospective_corroboration_not_pristine_holdout",
        "forward_shadow_candidate": True,
        "practice_promotion_eligible": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    report = run()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
