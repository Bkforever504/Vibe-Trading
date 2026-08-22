#!/usr/bin/env python3
"""Preregistered ATR exit overlays for the monthly technology swing baseline."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.higher_timeframe_volume_screen_lab import load_symbol, period_candidates
from research.swing_risk_overlay_lab import BASELINE, DEV_END, SELECTION_END, SYMBOLS, metrics


DEFAULT_OUTPUT = ROOT / "data" / "swing_exit_overlay_results.json"


@dataclass(frozen=True)
class ExitPolicy:
    name: str
    initial_atr_multiple: float | None = None
    chandelier_atr_multiple: float | None = None
    activation_atr_multiple: float | None = None
    profit_lock_atr_multiple: float | None = None


POLICIES = (
    ExitPolicy("fixed_20d"),
    ExitPolicy("initial_stop_2_5atr", initial_atr_multiple=2.5),
    ExitPolicy("chandelier_3atr", initial_atr_multiple=3.0, chandelier_atr_multiple=3.0),
    ExitPolicy(
        "asymmetric_profit_lock",
        initial_atr_multiple=2.5,
        activation_atr_multiple=3.0,
        profit_lock_atr_multiple=1.5,
    ),
)


def true_range(frame: pd.DataFrame) -> pd.Series:
    prior_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prior_close).abs(),
            (frame["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def simulate_asset(frame: pd.DataFrame, entry_pos: int, policy: ExitPolicy) -> dict[str, Any]:
    exit_limit = min(entry_pos + BASELINE.hold_days - 1, len(frame) - 1)
    entry = float(frame["open"].iloc[entry_pos])
    atr_series = true_range(frame).rolling(20).mean()
    initial_atr = float(atr_series.iloc[entry_pos - 1])
    if not np.isfinite(initial_atr) or initial_atr <= 0:
        raise ValueError("valid point-in-time ATR is required")
    active_stop = (
        entry - float(policy.initial_atr_multiple) * initial_atr
        if policy.initial_atr_multiple is not None
        else None
    )
    highest_completed_close = entry
    activated = False
    exit_price = float(frame["close"].iloc[exit_limit])
    exit_pos = exit_limit
    reason = "time_exit"

    for pos in range(entry_pos, exit_limit + 1):
        open_price = float(frame["open"].iloc[pos])
        low_price = float(frame["low"].iloc[pos])
        close_price = float(frame["close"].iloc[pos])
        if active_stop is not None and open_price <= active_stop:
            exit_price, exit_pos, reason = open_price, pos, "gap_stop"
            break
        if active_stop is not None and low_price <= active_stop:
            exit_price, exit_pos, reason = active_stop, pos, "intraday_stop"
            break
        if pos == exit_limit:
            exit_price, exit_pos, reason = close_price, pos, "time_exit"
            break

        highest_completed_close = max(highest_completed_close, close_price)
        current_atr = float(atr_series.iloc[pos])
        if not np.isfinite(current_atr) or current_atr <= 0:
            current_atr = initial_atr
        if policy.chandelier_atr_multiple is not None:
            candidate = highest_completed_close - policy.chandelier_atr_multiple * current_atr
            active_stop = max(float(active_stop), candidate)
        if policy.activation_atr_multiple is not None and policy.profit_lock_atr_multiple is not None:
            if close_price >= entry + policy.activation_atr_multiple * initial_atr:
                activated = True
            if activated:
                candidate = highest_completed_close - policy.profit_lock_atr_multiple * current_atr
                active_stop = max(float(active_stop), candidate)

    return {
        "return": exit_price / entry - 1.0,
        "entry": entry,
        "exit": exit_price,
        "exit_pos": exit_pos,
        "holding_sessions": exit_pos - entry_pos + 1,
        "reason": reason,
    }


def selected_by_date(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        if row["price_trend"] and row["period_return"] > 0:
            grouped.setdefault(row["decision_date"], []).append(row)
    return {
        decision_date: sorted(rows, key=lambda row: row["momentum"], reverse=True)[: BASELINE.top_n]
        for decision_date, rows in grouped.items()
    }


def replay(
    frames: dict[str, pd.DataFrame],
    grouped: dict[str, list[dict[str, Any]]],
    policy: ExitPolicy,
    *,
    cost_bps: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for decision_date, selected in sorted(grouped.items()):
        asset_results = []
        symbols = []
        for row in selected:
            frame = frames[row["symbol"]]
            entry_pos = int(row["entry_pos"])
            if entry_pos + BASELINE.hold_days > len(frame):
                continue
            asset_results.append(simulate_asset(frame, entry_pos, policy))
            symbols.append(row["symbol"])
        if not asset_results:
            continue
        weights = [1.0 / len(symbols)] * len(symbols)
        results.append(
            {
                "decision_date": decision_date,
                "return": float(np.mean([row["return"] for row in asset_results])) - cost_bps / 10_000,
                "exposure": 1.0,
                "weights": weights,
                "symbol_count": len(symbols),
                "symbols": symbols,
                "average_holding_sessions": float(np.mean([row["holding_sessions"] for row in asset_results])),
                "exit_reasons": [row["reason"] for row in asset_results],
            }
        )
    return results


def split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "development_2015_2022": metrics([row for row in rows if row["decision_date"] <= DEV_END]),
        "selection_2023_2025": metrics([row for row in rows if DEV_END < row["decision_date"] <= SELECTION_END]),
        "final_2026": metrics([row for row in rows if row["decision_date"] > SELECTION_END]),
    }


def drawdown_reduction(candidate: dict[str, Any], baseline: dict[str, Any], window: str) -> float:
    base = abs(float(baseline[window]["max_drawdown_pct"]))
    current = abs(float(candidate[window]["max_drawdown_pct"]))
    return (base - current) / base if base else 0.0


def build_report() -> dict[str, Any]:
    frames = {symbol: load_symbol(symbol, "2015-01-01", "2026-07-21", False) for symbol in SYMBOLS}
    candidates = [row for symbol, frame in frames.items() for row in period_candidates(symbol, frame, "monthly")]
    grouped = selected_by_date(candidates)
    rows: list[dict[str, Any]] = []
    for policy in POLICIES:
        normal = replay(frames, grouped, policy, cost_bps=10.0)
        stressed = replay(frames, grouped, policy, cost_bps=30.0)
        row = {"variant": policy.name, "rules": policy.__dict__, **split(normal), "stress": split(stressed)}
        rows.append(row)
    baseline = rows[0]
    for row in rows:
        reduction = drawdown_reduction(row, baseline, "selection_2023_2025")
        uplift = float(row["selection_2023_2025"]["ending_equity"]) - float(baseline["selection_2023_2025"]["ending_equity"])
        gates = {
            "selection_ending_equity_improved": uplift > 0,
            "selection_drawdown_reduced_20pct": reduction >= 0.20,
            "stress_positive_all_windows": all(
                (row["stress"][window].get("expectancy_bps") or 0) > 0
                for window in ("development_2015_2022", "selection_2023_2025", "final_2026")
            ),
            "positive_without_top_one_pct_all_windows": all(
                (row[window].get("top_one_pct_removed_expectancy_bps") or 0) > 0
                for window in ("development_2015_2022", "selection_2023_2025", "final_2026")
            ),
            "development_bootstrap_lower_bound_positive": (
                row["development_2015_2022"].get("bootstrap", {}).get("ci95_bps", [None])[0] or 0
            ) > 0,
            "selection_active_periods_gte_25": row["selection_2023_2025"].get("active_periods", 0) >= 25,
        }
        row["comparison"] = {
            "selection_ending_equity_uplift": round(uplift, 6),
            "selection_drawdown_reduction_pct": round(reduction * 100, 3),
        }
        row["gates"] = {**gates, "all_pass": all(gates.values())}
        row["shadow_candidate"] = row["variant"] != "fixed_20d" and all(gates.values())
    return {
        "schema_version": 1,
        "protocol": "SWING_EXIT_OVERLAY_PREREGISTRATION_2026-08-13",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "configuration_count": len(rows),
        "results": rows,
        "warnings": [
            "Adjusted OHLC stop fills are approximations, not broker quotes.",
            "The universe has survivorship bias.",
            "The 2026 comparison is not an independent pristine holdout.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps([
        {
            "variant": row["variant"],
            "selection": row["selection_2023_2025"],
            "final": row["final_2026"],
            "comparison": row["comparison"],
            "shadow_candidate": row["shadow_candidate"],
        }
        for row in report["results"]
    ], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
