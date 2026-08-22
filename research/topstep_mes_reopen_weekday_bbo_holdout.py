"""Score the frozen executable MES reopen weekday holdout."""

from __future__ import annotations

import json
from pathlib import Path

import databento as db
import pandas as pd

from research.topstep_mes_reopen_drift_lab import ROOT, summarize


SOURCE = ROOT / "data" / "databento" / "mes_v0_bbo1s_2026-07-18_2026-08-17.dbn.zst"
OUT = ROOT / "data" / "topstep_mes_reopen_weekday_bbo_holdout.json"
MANIFEST = ROOT / "data" / "databento_mes_reopen_holdout_manifest.json"
PREREGISTRATION = (
    "research/TOPSTEP_MES_REOPEN_WEEKDAY_BBO_HOLDOUT_2026-08-17.md"
)
ELIGIBLE_WEEKDAYS = {"Monday", "Wednesday", "Thursday"}
POINT_VALUE = 5.0
ROUND_TURN_FEE = 1.22
TICK_DOLLARS = 1.25


def _first_per_day(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["quote_timestamp"] = frame.index
    return frame.groupby(frame.index.date, sort=True).first().reset_index(drop=True)


def load_trades(path: Path = SOURCE) -> tuple[pd.DataFrame, dict]:
    frame = db.DBNStore.from_file(path).to_df()
    required = {"bid_px_00", "ask_px_00", "symbol"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"BBO holdout missing columns: {sorted(missing)}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError(f"expected DatetimeIndex, got {type(frame.index).__name__}")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    frame.index = frame.index.tz_convert("America/New_York")
    frame = frame[
        (frame["bid_px_00"] > 0)
        & (frame["ask_px_00"] > 0)
        & (frame["ask_px_00"] >= frame["bid_px_00"])
    ].sort_index()
    frame["symbol"] = frame["symbol"].astype(str)

    entries = _first_per_day(frame.between_time("18:00:05", "18:00:30")).rename(
        columns={
            "quote_timestamp": "entry_timestamp",
            "ask_px_00": "entry_ask",
            "symbol": "entry_symbol",
        }
    )
    exits = _first_per_day(frame.between_time("09:30:00", "09:30:10")).rename(
        columns={
            "quote_timestamp": "exit_timestamp",
            "bid_px_00": "exit_bid",
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
    ).dropna(subset=["exit_timestamp", "entry_ask", "exit_bid"])
    before_contract_check = len(paired)
    paired = paired[paired["entry_symbol"] == paired["exit_symbol"]].copy()
    paired["exit_weekday"] = paired["exit_timestamp"].dt.day_name()
    paired["eligible"] = paired["exit_weekday"].isin(ELIGIBLE_WEEKDAYS)
    paired["base_pnl"] = (
        (paired["exit_bid"] - paired["entry_ask"]) * POINT_VALUE - ROUND_TURN_FEE
    )
    paired["stress_1_pnl"] = paired["base_pnl"] - (2 * TICK_DOLLARS)
    paired["stress_2_pnl"] = paired["base_pnl"] - (4 * TICK_DOLLARS)
    return paired, {
        "raw_rows": int(len(frame)),
        "paired_before_contract_check": int(before_contract_check),
        "excluded_cross_contract_rows": int(before_contract_check - len(paired)),
        "paired_sessions": int(len(paired)),
    }


def _score(frame: pd.DataFrame) -> dict:
    return {
        "base": summarize(frame["base_pnl"]),
        "stress_1": summarize(frame["stress_1_pnl"]),
        "stress_2": summarize(frame["stress_2_pnl"]),
    }


def _support_gates(stats: dict) -> dict[str, bool]:
    return {
        "minimum_trades": stats["base"]["trades"] >= 10,
        "positive_base_expectancy": stats["base"]["avg_pnl"] > 0,
        "positive_stress_1_expectancy": stats["stress_1"]["avg_pnl"] > 0,
        "base_profit_factor": stats["base"]["profit_factor"] >= 1.05,
        "base_max_drawdown": stats["base"]["max_drawdown"] >= -500.0,
    }


def run(path: Path = SOURCE) -> dict:
    trades, integrity = load_trades(path)
    eligible = trades[trades["eligible"]]
    all_stats = _score(trades)
    eligible_stats = _score(eligible)
    gates = _support_gates(eligible_stats)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    degraded_dates = {
        row["date"]
        for row in manifest.get("dataset_conditions", [])
        if row.get("condition") != "available"
    }
    degraded_mask = eligible["exit_timestamp"].dt.strftime("%Y-%m-%d").isin(degraded_dates)
    clean_eligible = eligible[~degraded_mask]
    clean_stats = _score(clean_eligible)
    clean_gates = _support_gates(clean_stats)
    largest_winner = float(eligible["base_pnl"].max()) if not eligible.empty else 0.0
    total_pnl = float(eligible["base_pnl"].sum()) if not eligible.empty else 0.0
    largest_winner_share = largest_winner / total_pnl if total_pnl > 0 else 0.0
    clean_supportive = all(clean_gates.values())
    frozen_supportive = all(gates.values())
    return {
        "preregistration": PREREGISTRATION,
        "source": str(path.relative_to(ROOT)),
        "eligible_exit_weekdays": sorted(ELIGIBLE_WEEKDAYS),
        "source_integrity": integrity,
        "all_sessions": all_stats,
        "eligible_sessions": eligible_stats,
        "support_gates": gates,
        "bbo_holdout_supportive": frozen_supportive,
        "data_quality_sensitivity": {
            "non_available_dataset_dates": sorted(degraded_dates),
            "eligible_trades_on_non_available_dates": int(degraded_mask.sum()),
            "eligible_excluding_non_available_dates": clean_stats,
            "clean_support_gates": clean_gates,
            "clean_data_supportive": clean_supportive,
            "largest_winner_pnl": round(largest_winner, 2),
            "largest_winner_share_of_total_pnl": round(largest_winner_share, 4),
        },
        "forward_shadow_candidate": frozen_supportive,
        "practice_promotion_eligible": False,
        "practice_promotion_blockers": [
            "fewer_than_30_forward_resolved_outcomes",
            "positive_90pct_expectancy_lower_bound_not_established",
            "projectx_credentials_and_reconciliation_incomplete",
            "holdout_sensitive_to_degraded_day_and_largest_winner",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    report = run()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
