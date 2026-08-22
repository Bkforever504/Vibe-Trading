#!/usr/bin/env python3
"""Read-only QQQ mean-reversion baseline and challenger forward logger."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.qqq_mean_reversion_challenger_lab import (  # noqa: E402
    BASE_COST,
    VARIANTS,
    prepare_frame,
    signal_columns,
    simulate,
)
from scripts.market_data import data_source, fetch_ohlcv, fetch_vix_context  # noqa: E402


SYMBOL = "QQQ"
FORWARD_START = "2026-08-19"
LOG_PATH = ROOT / "data" / "qqq_mean_reversion_shadow_log.jsonl"
RESULTS_PATH = ROOT / "data" / "qqq_mean_reversion_challenger_results.json"
TRACKED = (
    "double7_baseline",
    "double7_exit_sma5",
    "rsi2_baseline",
    "rsi2_exit_prior_high",
)


def _variant(name: str):
    return next(item for item in VARIANTS if item.name == name)


def position_state(frame: pd.DataFrame, name: str) -> pd.Series:
    enter, exit_signal = signal_columns(frame, _variant(name))
    state = False
    values: list[bool] = []
    for timestamp in frame.index:
        if not state and bool(enter.loc[timestamp]):
            state = True
        elif state and bool(exit_signal.loc[timestamp]):
            state = False
        values.append(state)
    return pd.Series(values, index=frame.index, dtype=bool)


def _position_started_on(state: pd.Series) -> str | None:
    starts = state & ~state.shift(1, fill_value=False)
    matches = state.index[starts]
    return matches[-1].date().isoformat() if len(matches) else None


def _action(state: pd.Series) -> str:
    current = bool(state.iloc[-1])
    previous = bool(state.iloc[-2]) if len(state) > 1 else False
    started_on = _position_started_on(state)
    if current and not previous:
        return "arm_entry_next_open"
    if previous and not current:
        return "arm_exit_next_open"
    if current and started_on is not None and started_on < FORWARD_START:
        return "inherited_virtual_long_observe_only"
    return "hold_virtual_long" if current else "flat"


def _development_metrics() -> dict[str, Any]:
    if not RESULTS_PATH.exists():
        return {}
    try:
        report = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        row["variant"]: row.get("development", {})
        for row in report.get("results", [])
        if row.get("variant") in TRACKED
    }


def compute_records(ohlcv: pd.DataFrame, symbol: str = SYMBOL) -> list[dict[str, Any]]:
    frame = prepare_frame(ohlcv)
    if len(frame) < 225:
        raise ValueError("Insufficient bars for QQQ mean-reversion warmup")
    as_of = frame.index[-1].date().isoformat()
    metrics = _development_metrics()
    setups: dict[str, Any] = {}
    for name in TRACKED:
        state = position_state(frame, name)
        started_on = _position_started_on(state)
        development = metrics.get(name, {})
        setups[name] = {
            "action": _action(state),
            "in_position_after_close": bool(state.iloc[-1]),
            "position_state_started_on": started_on,
            "forward_outcome_eligible": bool(started_on is not None and started_on >= FORWARD_START),
            "execution_enabled": False,
            "can_submit_orders": False,
            "development_evidence": {
                "trades": development.get("trades"),
                "expectancy_per_10000": development.get("expectancy"),
                "profit_factor": development.get("profit_factor"),
                "max_drawdown_per_10000": development.get("max_drawdown"),
                "multiple_test_promoted": False,
            },
        }
    latest = frame.iloc[-1]
    snapshot: dict[str, Any] = {
        "record_type": "signal",
        "status": "shadow_signal",
        "date": as_of,
        "symbol": symbol,
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "data_source": data_source(),
        "vix_context": fetch_vix_context(),
        "features": {
            "close": round(float(latest["close"]), 4),
            "rsi2": round(float(latest["rsi2"]), 4),
            "sma5": round(float(latest["sma5"]), 4),
            "sma200": round(float(latest["sma200"]), 4),
            "sma200_rising20": bool(latest["sma200_rising20"]),
            "atr20": round(float(latest["atr20"]), 4),
            "annualized_vol20": round(float(latest["vol20"]), 6),
            "drawdown_from_20d_high": round(float(latest["drawdown20"]), 6),
            "at_7d_closing_low": bool(latest["close"] <= latest["low7"]),
            "at_7d_closing_high": bool(latest["close"] >= latest["high7"]),
        },
        "setups": setups,
        "promotion_contract": {
            "minimum_logged_trading_days": 30,
            "minimum_completed_forward_trades": 10,
            "requires_explicit_human_approval": True,
            "development_result_can_promote": False,
        },
    }
    records = [snapshot]
    for name in TRACKED:
        for trade in simulate(frame, _variant(name)):
            if trade["entry_date"] < FORWARD_START or trade["exit_date"] != as_of:
                continue
            records.append({
                "record_type": "outcome",
                "status": "resolved",
                "date": as_of,
                "symbol": symbol,
                "variant": name,
                "entry_date": trade["entry_date"],
                "exit_date": trade["exit_date"],
                "gross_pnl_per_10000": round(float(trade["gross_pnl"]), 2),
                "net_pnl_per_10000": round(float(trade["gross_pnl"] - BASE_COST * trade["exposure"]), 2),
                "holding_sessions": trade["holding_sessions"],
                "mae_pct": round(float(trade["mae_pct"]) * 100, 3),
                "mfe_pct": round(float(trade["mfe_pct"]) * 100, 3),
                "execution_enabled": False,
                "can_submit_orders": False,
            })
    return records


def record_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("record_type"), row.get("date"), row.get("variant"), row.get("entry_date"))


def write_records(records: list[dict[str, Any]], path: Path = LOG_PATH) -> None:
    existing: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                existing.append(row)
    replacements = {record_key(row): row for row in records}
    merged = [row for row in existing if record_key(row) not in replacements]
    merged.extend(records)
    merged.sort(key=lambda row: (str(row.get("date", "")), str(row.get("record_type", "")), str(row.get("variant", ""))))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in merged), encoding="utf-8")


def main() -> int:
    records = compute_records(fetch_ohlcv(SYMBOL, lookback_days=900))
    write_records(records)
    snapshot = records[0]
    print(json.dumps({
        "date": snapshot["date"],
        "symbol": SYMBOL,
        "setups": {name: row["action"] for name, row in snapshot["setups"].items()},
        "new_resolved_outcomes": len(records) - 1,
        "mode": "shadow_only",
        "log_path": str(LOG_PATH),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
