#!/usr/bin/env python3
"""Source-matched transfer test of SwiftCap's public X-PDBO MQL5 rules.

The source appears designed for MetaTrader/CFD use. This lab tests whether the
same hypothesis transfers to one-contract MES with explicit costs. It has no
broker imports and no execution authority.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_OUTPUT = ROOT / "data" / "x_pdbo_source_matched_results.json"
SOURCE_URL = "https://swiftcapeas.com/free-download?product=x-pdbo-ea"
TICK = 0.25
POINT_VALUE = 5.0
ROUND_TRIP_FEES = 2.48
ROUND_TRIP_SLIPPAGE = 2 * TICK * POINT_VALUE


@dataclass(frozen=True)
class Variant:
    name: str
    timeframe_minutes: int
    trigger: str
    use_atr_contraction: bool


@dataclass(frozen=True)
class Trade:
    session: str
    side: int
    entry: float
    exit: float
    risk_points: float
    gross_points: float
    exit_reason: str


VARIANTS = (
    Variant("source_open_check_1m", 1, "bar_open", True),
    Variant("source_open_check_5m", 5, "bar_open", True),
    Variant("source_open_check_15m", 15, "bar_open", True),
    Variant("comment_cross_interpretation_1m", 1, "intrabar_cross", True),
    Variant("no_atr_filter_control_1m", 1, "bar_open", False),
)


def wilder_atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    result = pd.Series(float("nan"), index=true_range.index, dtype=float)
    if len(true_range) < period:
        return result
    seed = float(true_range.iloc[:period].mean())
    result.iloc[period - 1] = seed
    for index in range(period, len(true_range)):
        result.iloc[index] = (
            result.iloc[index - 1] * (period - 1) + float(true_range.iloc[index])
        ) / period
    return result


def _resample_session(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return frame.reset_index(drop=True)
    return (
        frame.set_index("timestamp")
        .resample(f"{minutes}min", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )


def simulate_session(
    bars: pd.DataFrame,
    *,
    session: str,
    previous_high: float,
    previous_low: float,
    reward_risk: float = 3.0,
    trigger: str = "bar_open",
) -> Trade | None:
    if previous_high <= previous_low or bars.empty:
        return None
    entry_index = None
    side = 0
    entry = 0.0
    for index, bar in bars.iterrows():
        if trigger == "bar_open":
            if float(bar["open"]) > previous_high:
                side, entry = 1, float(bar["open"])
            elif float(bar["open"]) < previous_low:
                side, entry = -1, float(bar["open"])
        elif trigger == "intrabar_cross":
            crossed_high = float(bar["high"]) > previous_high
            crossed_low = float(bar["low"]) < previous_low
            if crossed_high and crossed_low:
                continue
            if crossed_high:
                side = 1
                entry = max(float(bar["open"]), previous_high)
            elif crossed_low:
                side = -1
                entry = min(float(bar["open"]), previous_low)
        else:
            raise ValueError(f"unknown trigger: {trigger}")
        if side:
            entry_index = index
            break
    if entry_index is None:
        return None

    stop = previous_low if side > 0 else previous_high
    risk_points = abs(entry - stop)
    if risk_points <= 0:
        return None
    target = entry + side * reward_risk * risk_points
    exit_price = float(bars.iloc[-1]["close"])
    exit_reason = "end_of_day"
    for _, bar in bars.loc[entry_index:].iterrows():
        if side > 0:
            stop_hit = float(bar["low"]) <= stop
            target_hit = float(bar["high"]) >= target
        else:
            stop_hit = float(bar["high"]) >= stop
            target_hit = float(bar["low"]) <= target
        # OHLC cannot establish ordering. Resolve ambiguous bars adversely.
        if stop_hit:
            exit_price, exit_reason = stop, "stop"
            break
        if target_hit:
            exit_price, exit_reason = target, "target_3r"
            break
    return Trade(
        session=session,
        side=side,
        entry=entry,
        exit=exit_price,
        risk_points=risk_points,
        gross_points=side * (exit_price - entry),
        exit_reason=exit_reason,
    )


def _max_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def metrics(trades: list[Trade], cost_multiplier: float = 1.0) -> dict[str, Any]:
    cost = (ROUND_TRIP_FEES + ROUND_TRIP_SLIPPAGE) * cost_multiplier
    pnls = [trade.gross_points * POINT_VALUE - cost for trade in trades]
    wins = sum(value > 0 for value in pnls)
    gross_wins = sum(value for value in pnls if value > 0)
    gross_losses = -sum(value for value in pnls if value < 0)
    top_trimmed = sorted(pnls)[: -max(1, math.ceil(len(pnls) * 0.01))] if pnls else []
    return {
        "trades": len(trades),
        "total_pnl_dollars": round(sum(pnls), 2),
        "expectancy_dollars": round(mean(pnls), 4) if pnls else None,
        "win_rate": round(wins / len(pnls), 4) if pnls else None,
        "profit_factor": round(gross_wins / gross_losses, 4) if gross_losses else None,
        "max_drawdown_dollars": round(_max_drawdown(pnls), 2),
        "average_initial_risk_dollars": round(mean(trade.risk_points * POINT_VALUE for trade in trades), 2)
        if trades else None,
        "risk_1000_compatible_rate": round(
            sum(trade.risk_points * POINT_VALUE <= 1000.0 for trade in trades) / len(trades), 4
        ) if trades else None,
        "exit_reasons": {
            reason: sum(trade.exit_reason == reason for trade in trades)
            for reason in ("stop", "target_3r", "end_of_day")
        },
        "top_one_pct_removed_expectancy_dollars": round(mean(top_trimmed), 4) if top_trimmed else None,
    }


def _split(trades: list[Trade]) -> dict[str, list[Trade]]:
    return {
        "development_2022_2024": [trade for trade in trades if trade.session <= "2024-12-31"],
        "selection_2025": [trade for trade in trades if "2025-01-01" <= trade.session <= "2025-12-31"],
        "final_2026": [trade for trade in trades if trade.session >= "2026-01-01"],
    }


def run_lab(csv_path: Path = DEFAULT_CSV) -> dict[str, Any]:
    raw = pd.read_csv(csv_path)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"])
    raw["session"] = raw["timestamp"].dt.date.astype(str)
    daily = (
        raw.groupby("session", sort=True)
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .reset_index()
    )
    daily["atr5"] = wilder_atr(daily, 5)
    daily["atr10"] = wilder_atr(daily, 10)
    daily["previous_high"] = daily["high"].shift(1)
    daily["previous_low"] = daily["low"].shift(1)
    daily["entry_atr5"] = daily["atr5"].shift(1)
    daily["entry_atr10"] = daily["atr10"].shift(1)
    context = {row["session"]: row for _, row in daily.iterrows()}
    session_frames = {session: frame.copy() for session, frame in raw.groupby("session", sort=True)}

    reports = []
    for variant in VARIANTS:
        trades: list[Trade] = []
        eligible_sessions = 0
        for session, frame in session_frames.items():
            row = context[session]
            values = (row["previous_high"], row["previous_low"], row["entry_atr5"], row["entry_atr10"])
            if any(pd.isna(value) for value in values):
                continue
            contraction = float(row["entry_atr5"]) < float(row["entry_atr10"])
            if variant.use_atr_contraction and not contraction:
                continue
            eligible_sessions += 1
            bars = _resample_session(frame.drop(columns=["session"]), variant.timeframe_minutes)
            trade = simulate_session(
                bars,
                session=session,
                previous_high=float(row["previous_high"]),
                previous_low=float(row["previous_low"]),
                trigger=variant.trigger,
            )
            if trade is not None:
                trades.append(trade)
        split_reports = {name: metrics(values) for name, values in _split(trades).items()}
        overall = metrics(trades)
        double_cost = metrics(trades, 2.0)
        split_pass = all(
            report["trades"] >= 30
            and (report["expectancy_dollars"] or 0) > 0
            and (report["profit_factor"] or 0) > 1
            for report in split_reports.values()
        )
        passed = (
            split_pass
            and (double_cost["expectancy_dollars"] or 0) > 0
            and (overall["top_one_pct_removed_expectancy_dollars"] or 0) > 0
        )
        reports.append({
            "variant": asdict(variant),
            "eligible_session_count": eligible_sessions,
            "overall": overall,
            "double_cost": double_cost,
            "splits": split_reports,
            "passed": passed,
            "promotion_authority": "human_review_only" if passed else "blocked",
        })
    return {
        "schema_version": 1,
        "experiment": "SWIFTCAP-X-PDBO-SOURCE-MATCHED-MES-TRANSFER",
        "source_url": SOURCE_URL,
        "source_rules": {
            "entry": "first bar check beyond previous RTH session high or low",
            "filter": "completed_daily_wilder_atr_5_below_atr_10",
            "stop": "opposite_side_of_previous_session_range",
            "target": "three_times_initial_risk",
            "exit": "stop_target_or_rth_end_of_day",
            "one_trade_per_day": True,
        },
        "cost_model": {
            "instrument": "MES_one_contract",
            "point_value": POINT_VALUE,
            "round_trip_fees": ROUND_TRIP_FEES,
            "round_trip_slippage": ROUND_TRIP_SLIPPAGE,
        },
        "dataset": str(csv_path),
        "dataset_session_count": len(session_frames),
        "variants": reports,
        "survivor_count": sum(report["passed"] for report in reports),
        "limitations": [
            "The public EA does not specify chart timeframe; 1m, 5m, and 15m are implementation-uncertainty tests.",
            "The filename suggests a MetaTrader FX/CFD origin; this is a transfer test on MES, not replication on its original market.",
            "RTH daily boundaries replace broker-server D1 boundaries so levels are executable for CME research.",
            "OHLC bars use adverse ordering when stop and target are both touched.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run_lab(args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
