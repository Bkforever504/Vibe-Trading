#!/usr/bin/env python3
"""One-shot test of the preregistered MES signed-flow absorption rule."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "data" / "databento" / "mes_signed_flow_windows_2025q4.parquet"
QUOTES = ROOT / "data" / "databento" / "mes_v0_bbo1s_rth.parquet"
OUT = ROOT / "data" / "mes_absorption_phase_b_results.json"

MIN_VOLUME = 5_000
MIN_ABS_IMBALANCE = 0.40
MAX_ABS_DISPLACEMENT = 0.50
HOLD_MINUTES = 5
MAX_SIGNALS_DAY = 3
POINT_USD = 5.0
TICK = 0.25
BASE_COMMISSION = 2.48
STRESS_COMMISSION = 4.96


def select_non_overlapping(candidates: pd.DataFrame) -> pd.DataFrame:
    selected: list[int] = []
    for _, session in candidates.sort_values("signal_ts").groupby("session_date", sort=True):
        busy_until = None
        count = 0
        for index, row in session.iterrows():
            if count >= MAX_SIGNALS_DAY:
                break
            signal_ts = row["signal_ts"]
            if busy_until is not None and signal_ts < busy_until:
                continue
            selected.append(index)
            busy_until = signal_ts + pd.Timedelta(minutes=HOLD_MINUTES)
            count += 1
    return candidates.loc[selected].sort_values("signal_ts").reset_index(drop=True)


def trade_pnl(
    *, direction: int, entry_bid: float, entry_ask: float,
    exit_bid: float, exit_ask: float, stress: bool,
) -> float:
    entry = entry_ask if direction > 0 else entry_bid
    exit_price = exit_bid if direction > 0 else exit_ask
    gross = direction * (exit_price - entry) * POINT_USD
    if stress:
        gross -= 2 * TICK * POINT_USD
    return gross - (STRESS_COMMISSION if stress else BASE_COMMISSION)


def metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"trades": 0}
    wins = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value <= 0)
    equity = pd.Series(values).cumsum()
    return {
        "trades": len(values),
        "total_pnl": round(sum(values), 2),
        "expectancy": round(sum(values) / len(values), 2),
        "win_rate": round(sum(value > 0 for value in values) / len(values), 4),
        "profit_factor": round(wins / losses, 4) if losses else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
    }


def passes(result: dict[str, Any], stressed: dict[str, Any], minimum_trades: int) -> bool:
    return bool(
        result.get("trades", 0) >= minimum_trades
        and result.get("expectancy", 0) > 0
        and (result.get("profit_factor") or 0) >= 1.20
        and stressed.get("expectancy", 0) > 0
    )


def fill_signals(connection: Any, selected: pd.DataFrame) -> pd.DataFrame:
    if selected.empty:
        empty = selected.copy()
        empty["base_pnl"] = pd.Series(dtype=float)
        empty["stress_pnl"] = pd.Series(dtype=float)
        return empty
    connection.register("selected_input", selected)
    filled = connection.execute(
        f"""
        WITH quotes AS (
          SELECT
            CAST(timezone('America/New_York', ts_recv) AS DATE) AS session_date,
            timezone('America/New_York', ts_recv) AS local_ts,
            bid_px_00 AS bid,
            ask_px_00 AS ask
          FROM read_parquet('{QUOTES.as_posix()}')
          WHERE bid_px_00 > 0 AND ask_px_00 > bid_px_00
        ), entries AS (
          SELECT s.*, q.local_ts AS entry_ts, q.bid AS entry_bid, q.ask AS entry_ask
          FROM selected_input s
          ASOF LEFT JOIN quotes q
            ON s.session_date = q.session_date AND s.signal_ts <= q.local_ts
        )
        SELECT e.*, q.local_ts AS exit_ts, q.bid AS exit_bid, q.ask AS exit_ask
        FROM entries e
        ASOF LEFT JOIN quotes q
          ON e.session_date = q.session_date
         AND e.signal_ts + INTERVAL {HOLD_MINUTES} MINUTE <= q.local_ts
        ORDER BY signal_ts
        """
    ).fetchdf()
    connection.unregister("selected_input")
    filled = filled.dropna(subset=["entry_bid", "entry_ask", "exit_bid", "exit_ask"])
    filled["base_pnl"] = filled.apply(
        lambda row: trade_pnl(
            direction=int(row["direction"]), entry_bid=float(row["entry_bid"]),
            entry_ask=float(row["entry_ask"]), exit_bid=float(row["exit_bid"]),
            exit_ask=float(row["exit_ask"]), stress=False,
        ), axis=1,
    )
    filled["stress_pnl"] = filled.apply(
        lambda row: trade_pnl(
            direction=int(row["direction"]), entry_bid=float(row["entry_bid"]),
            entry_ask=float(row["entry_ask"]), exit_bid=float(row["exit_bid"]),
            exit_ask=float(row["exit_ask"]), stress=True,
        ), axis=1,
    )
    return filled


def run() -> dict[str, Any]:
    import duckdb

    connection = duckdb.connect()
    connection.execute("SET TimeZone='America/New_York'")
    candidates = connection.execute(
        f"""
        SELECT
          session_date,
          window_start + INTERVAL 1 MINUTE AS signal_ts,
          CASE WHEN signed_imbalance > 0 THEN -1 ELSE 1 END AS direction,
          total_aggressive_volume,
          signed_imbalance,
          mid_displacement
        FROM read_parquet('{WINDOWS.as_posix()}')
        WHERE total_aggressive_volume >= {MIN_VOLUME}
          AND abs(signed_imbalance) >= {MIN_ABS_IMBALANCE}
          AND abs(mid_displacement) <= {MAX_ABS_DISPLACEMENT}
          AND CAST(window_start AS TIME) < TIME '15:25:00'
        ORDER BY signal_ts
        """
    ).fetchdf()
    selected = select_non_overlapping(candidates)
    sessions = [
        str(value) for value in connection.execute(
            f"SELECT DISTINCT session_date FROM read_parquet('{WINDOWS.as_posix()}') ORDER BY session_date"
        ).fetchnumpy()["session_date"]
    ]
    split = int(len(sessions) * 0.70)
    development_dates = set(sessions[:split])
    development_selected = selected[
        selected["session_date"].astype(str).isin(development_dates)
    ]
    development = fill_signals(connection, development_selected)

    dev_base = metrics(development["base_pnl"].tolist())
    dev_stress = metrics(development["stress_pnl"].tolist())
    dev_pass = passes(dev_base, dev_stress, 30)
    result: dict[str, Any] = {
        "protocol": "MES_SIGNED_FLOW_ABSORPTION_PHASE_B_2026-07-21",
        "routing_authority": False,
        "parameters": {
            "minimum_aggressive_volume": MIN_VOLUME,
            "minimum_absolute_imbalance": MIN_ABS_IMBALANCE,
            "maximum_absolute_mid_displacement": MAX_ABS_DISPLACEMENT,
            "hold_minutes": HOLD_MINUTES,
            "maximum_signals_per_day": MAX_SIGNALS_DAY,
        },
        "candidate_windows": int(len(candidates)),
        "development_calendar_sessions": split,
        "development_filled_signals": int(len(development)),
        "development": dev_base,
        "development_stressed": dev_stress,
        "development_pass": dev_pass,
        "final_opened": dev_pass,
        "promotion_allowed": False,
    }
    if candidates.empty:
        result["verdict"] = "rejected_infeasible_zero_candidate_windows"
        result["final_opened"] = False
        OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    if dev_pass:
        final_selected = selected[
            ~selected["session_date"].astype(str).isin(development_dates)
        ]
        final = fill_signals(connection, final_selected)
        final_base = metrics(final["base_pnl"].tolist())
        final_stress = metrics(final["stress_pnl"].tolist())
        result.update({
            "final_calendar_sessions": len(sessions) - split,
            "final_filled_signals": int(len(final)),
            "final": final_base,
            "final_stressed": final_stress,
            "final_pass": passes(final_base, final_stress, 15),
        })
    else:
        result["verdict"] = "rejected_without_opening_final_segment"

    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
