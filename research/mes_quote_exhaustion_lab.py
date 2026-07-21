#!/usr/bin/env python3
"""Selection-gated MES quote-imbalance exhaustion replay.

Research only. The frozen specification is documented in
MES_QUOTE_EXHAUSTION_PREREGISTRATION_2026-07-20.md.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import mes_orderflow_lab as bbo


PREREGISTRATION = ROOT / "research" / "MES_QUOTE_EXHAUSTION_PREREGISTRATION_2026-07-20.md"
OUT = ROOT / "data" / "mes_quote_exhaustion_results.json"

THRESHOLD = 0.10
WINDOW_OBSERVATIONS = 300
HOLD_SECONDS = 300
STOP_TICKS = 20
MAX_TRADES_PER_DAY = 3
SIGNAL_START = 9 * 3600 + 35 * 60
SIGNAL_END = 15 * 3600 + 30 * 60
FLATTEN_TIME = 15 * 3600 + 55 * 60
MIN_STAGE_TRADES = 30
MIN_PROFIT_FACTOR = 1.20
MAX_DRAWDOWN_USD = 200.0
MAX_SESSION_LOSS_USD = 100.0
MAX_CONSISTENCY_FRACTION = 0.50


def chronological_splits(sessions: list[str]) -> tuple[list[str], list[str], list[str]]:
    dev_end = int(len(sessions) * 0.70)
    selection_end = int(len(sessions) * 0.85)
    return sessions[:dev_end], sessions[dev_end:selection_end], sessions[selection_end:]


def replay_session(session: pd.DataFrame) -> list[dict[str, Any]]:
    ordered = session.sort_values("sec")
    sec = ordered["sec"].to_numpy()
    bid = ordered["bid"].to_numpy(dtype=float)
    ask = ordered["ask"].to_numpy(dtype=float)
    mid = (bid + ask) / 2.0
    rolling = (
        pd.Series(ordered["imb"].to_numpy(dtype=float))
        .rolling(WINDOW_OBSERVATIONS, min_periods=WINDOW_OBSERVATIONS)
        .mean()
        .to_numpy()
    )
    trades: list[dict[str, Any]] = []
    busy_until = -1
    i = WINDOW_OBSERVATIONS
    while i < len(sec) and len(trades) < MAX_TRADES_PER_DAY:
        if sec[i] < SIGNAL_START or sec[i] >= SIGNAL_END or sec[i] < busy_until:
            i += 1
            continue
        previous = rolling[i - 1]
        current = rolling[i]
        crossed_positive = previous < THRESHOLD <= current
        crossed_negative = previous > -THRESHOLD >= current
        if not crossed_positive and not crossed_negative:
            i += 1
            continue

        # Positive bid-size imbalance is faded with a short; negative with a long.
        direction = -1 if crossed_positive else 1
        entry = ask[i] if direction > 0 else bid[i]
        stop_points = STOP_TICKS * bbo.TICK
        stop = entry - direction * stop_points
        time_exit = min(sec[i] + HOLD_SECONDS, FLATTEN_TIME)
        last = min(int(np.searchsorted(sec, time_exit)), len(sec) - 1)
        exit_index = last
        exit_reason = "time_exit"
        for j in range(i + 1, last + 1):
            stopped = mid[j] <= stop if direction > 0 else mid[j] >= stop
            if stopped:
                exit_index = j
                exit_reason = "hard_stop"
                break
        exit_price = bid[exit_index] if direction > 0 else ask[exit_index]
        gross_points = direction * (exit_price - entry)
        trades.append({
            "entry_sec": int(sec[i]),
            "exit_sec": int(sec[exit_index]),
            "direction": "long" if direction > 0 else "short",
            "rolling_imbalance": round(float(current), 6),
            "entry_price": float(entry),
            "exit_price": float(exit_price),
            "exit_reason": exit_reason,
            "gross_points": round(float(gross_points), 6),
            "gross_usd": round(float(gross_points * bbo.POINT_USD), 6),
        })
        busy_until = int(sec[exit_index])
        i = exit_index + 1
    return trades


def stage_stats(trades_by_date: dict[str, list[dict[str, Any]]], dates: list[str], *, stress: bool) -> dict[str, Any]:
    cost = bbo.cost_usd(True, stress)
    pnl: list[float] = []
    daily: dict[str, float] = {}
    stop_count = 0
    for day in dates:
        values = []
        for trade in trades_by_date.get(day, []):
            value = float(trade["gross_usd"]) - cost
            pnl.append(value)
            values.append(value)
            stop_count += trade.get("exit_reason") == "hard_stop"
        if values:
            daily[day] = sum(values)
    if not pnl:
        return {"trades": 0, "trading_days": 0}
    wins = sum(value for value in pnl if value > 0)
    losses = -sum(value for value in pnl if value <= 0)
    cumulative = np.concatenate(([0.0], np.cumsum(pnl)))
    peaks = np.maximum.accumulate(cumulative)
    total = float(sum(pnl))
    positive_days = [value for value in daily.values() if value > 0]
    best_day = max(positive_days, default=0.0)
    consistency = best_day / total if total > 0 else None
    return {
        "trades": len(pnl),
        "trading_days": len(daily),
        "total_pnl": round(total, 2),
        "expectancy": round(total / len(pnl), 2),
        "win_rate": round(sum(value > 0 for value in pnl) / len(pnl), 4),
        "profit_factor": round(wins / losses, 4) if losses > 0 else None,
        "max_drawdown": round(float(np.max(peaks - cumulative)), 2),
        "worst_session_pnl": round(min(daily.values()), 2),
        "best_session_pnl": round(max(daily.values()), 2),
        "best_day_consistency_fraction": round(consistency, 4) if consistency is not None else None,
        "hard_stop_count": int(stop_count),
        "cost_per_trade": round(cost, 2),
    }


def stage_passed(base: dict[str, Any], stressed: dict[str, Any]) -> tuple[bool, list[str]]:
    max_drawdown = base.get("max_drawdown")
    worst_session = base.get("worst_session_pnl")
    checks = {
        "minimum_trades": int(base.get("trades") or 0) >= MIN_STAGE_TRADES,
        "positive_expectancy": float(base.get("expectancy") or 0.0) > 0,
        "profit_factor": float(base.get("profit_factor") or 0.0) >= MIN_PROFIT_FACTOR,
        "positive_stressed_expectancy": float(stressed.get("expectancy") or 0.0) > 0,
        "drawdown": max_drawdown is not None and float(max_drawdown) <= MAX_DRAWDOWN_USD,
        "session_loss": worst_session is not None and float(worst_session) >= -MAX_SESSION_LOSS_USD,
        "consistency": (
            base.get("best_day_consistency_fraction") is not None
            and float(base["best_day_consistency_fraction"]) <= MAX_CONSISTENCY_FRACTION
        ),
    }
    return all(checks.values()), [name for name, passed in checks.items() if not passed]


def evaluate(
    trades_by_date: dict[str, list[dict[str, Any]]],
    sessions: list[str],
    *,
    final_trades_by_date: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    development, selection, final = chronological_splits(sessions)
    selection_base = stage_stats(trades_by_date, selection, stress=False)
    selection_stressed = stage_stats(trades_by_date, selection, stress=True)
    selection_pass, selection_failures = stage_passed(selection_base, selection_stressed)
    result: dict[str, Any] = {
        "development": {
            "session_count": len(development),
            "outcomes_opened": False,
            "reason": "consumed_discovery_period_not_independent_evidence",
        },
        "selection": selection_base,
        "selection_stressed": selection_stressed,
        "selection_pass": selection_pass,
        "selection_failed_checks": selection_failures,
        "final": {
            "session_count": len(final),
            "outcomes_opened": False,
            "reason": "sealed_until_selection_passes",
        },
    }
    if not selection_pass:
        return result
    if final_trades_by_date is None:
        result["final"]["reason"] = "selection_passed_but_final_data_not_loaded"
        return result
    final_base = stage_stats(final_trades_by_date, final, stress=False)
    final_stressed = stage_stats(final_trades_by_date, final, stress=True)
    final_pass, final_failures = stage_passed(final_base, final_stressed)
    result.update({
        "final": {**final_base, "outcomes_opened": True},
        "final_stressed": final_stressed,
        "final_pass": final_pass,
        "final_failed_checks": final_failures,
    })
    return result


def main() -> None:
    bbo.build_parquet()
    data = bbo.load_seconds()
    excluded = bbo.excluded_sessions()
    coverage = data.groupby("date")["sec"].count()
    complete = {day for day, count in coverage.items() if count >= 0.8 * 6.5 * 3600}
    sessions = sorted(day for day in complete if day not in excluded)
    data = data[data["date"].isin(sessions)]
    _, selection_dates, final_dates = chronological_splits(sessions)
    selection_data = data[data["date"].isin(selection_dates)]
    trades_by_date = {
        day: replay_session(frame)
        for day, frame in selection_data.groupby("date")
    }
    evaluation = evaluate(trades_by_date, sessions)
    if evaluation.get("selection_pass") is True:
        final_data = data[data["date"].isin(final_dates)]
        final_trades = {
            day: replay_session(frame)
            for day, frame in final_data.groupby("date")
        }
        evaluation = evaluate(trades_by_date, sessions, final_trades_by_date=final_trades)
    prereg_hash = hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest().upper()
    result = {
        "provider": "mes_quote_exhaustion_lab",
        "mode": "research_only_no_execution",
        "preregistration": str(PREREGISTRATION.relative_to(ROOT)),
        "preregistration_sha256": prereg_hash,
        "data": {
            "source": str(bbo.DBN.relative_to(ROOT)),
            "sessions": len(sessions),
            "excluded_roll_or_condition": len(excluded),
            "excluded_low_coverage": int(len(coverage) - len(complete)),
        },
        "frozen_config": {
            "threshold": THRESHOLD,
            "window_observations": WINDOW_OBSERVATIONS,
            "direction": "fade",
            "stop_ticks": STOP_TICKS,
            "hold_seconds": HOLD_SECONDS,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
        },
        "evaluation": evaluation,
        "execution_enabled": False,
        "promotion_allowed": False,
        "next_action": (
            "collect_30_later_ninjatrader_sim101_trades"
            if evaluation.get("final_pass") is True
            else "reject_specification_keep_mes_execution_disabled"
        ),
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
